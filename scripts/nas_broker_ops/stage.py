#!/usr/bin/python3
"""Private password candidate + isolated exact-image/TLS validation; no live edits."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,pwd,re,shutil,stat,subprocess,uuid
DOCKER='/usr/local/bin/docker'
IMAGE='sha256:4725ea7590a578122675b1fdd242b94e5034885cfd0806045b25d700f5498ef5'
CONFIG=Path('/volume1/docker/mosquitto/config')
VAULT=Path('/volume1/docker/smart-gatekeeper-backend/secrets')
OPS=Path('/usr/local/lib/smart-gatekeeper-broker-ops')
BASE=OPS/'incoming'
STATE=OPS/'state'
LAST_ERROR=None
def call(args,input=None,timeout=30):
 result=subprocess.run(args,input=input,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
 if result.returncode:
  global LAST_ERROR
  LAST_ERROR={'command':args,'stdout':result.stdout.decode('utf-8','replace')[-2000:],
              'stderr':result.stderr.decode('utf-8','replace')[-2000:]}
  raise RuntimeError('private candidate command failed')
 return result.stdout.decode('utf-8')
def write(path,value):
 fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:f.write(value)
def metadata(path):
 info=path.stat()
 return {'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'uid':info.st_uid,
         'gid':info.st_gid,'mode':oct(stat.S_IMODE(info.st_mode))}
def report(data,suffix):
 output=STATE/('stage-'+suffix+'.json')
 temporary=STATE/('report-'+uuid.uuid4().hex)
 data['input_sha256']=hashlib.sha256((BASE/'inventory.json').read_bytes()+b'\0'+(BASE/'credentials-new.json').read_bytes()).hexdigest()
 write(temporary,json.dumps(data,sort_keys=True))
 os.replace(str(temporary),str(output))
SDK=r"""
import json,ssl,socket,threading,time,uuid
from pathlib import Path
import paho.mqtt.client as mqtt
profile=json.loads(Path('/policy/probe.json').read_text())
credentials=json.loads(Path('/policy/credentials.json').read_text())
hostname=profile['hostname'];ports=profile['ports']
saved=socket.getaddrinfo
def resolve(host,port,*args,**kwargs):
 if host==hostname and int(port)==ports['tls']:host='127.0.0.1'
 return saved(host,port,*args,**kwargs)
socket.getaddrinfo=resolve
for port in ports.values():
 deadline=time.monotonic()+15
 while True:
  try:
   with socket.create_connection(('127.0.0.1',port),timeout=.2):break
  except OSError:
   if time.monotonic()>deadline:raise RuntimeError('private broker did not listen')
   time.sleep(.1)
count=0
for transport,port in ports.items():
 cases=[(name,value,True) for name,value in credentials.items()]
 cases.extend([(None,None,False),(next(iter(credentials)),'wrong-password',False)])
 for username,password,allowed in cases:
  ready=threading.Event();results=[]
  client=mqtt.Client(client_id='candidate-'+uuid.uuid4().hex[:12],clean_session=True)
  if username is not None:client.username_pw_set(username,password)
  if transport=='tls':client.tls_set_context(ssl.create_default_context(cafile='/client-ca.pem'))
  client.on_connect=lambda c,u,f,rc:(results.append(rc),ready.set())
  client.connect(hostname if transport=='tls' else '127.0.0.1',port,keepalive=10)
  client.loop_start()
  try:
   if not ready.wait(8):raise RuntimeError('private CONNECT deadline')
   if (results[0]==0)!=allowed:raise RuntimeError('private credential acceptance mismatch')
  finally:
   client.disconnect();client.loop_stop()
  count+=1
print(json.dumps({'isolated_auth_cases':count,'both_listeners_verified':True,'tls_hostname_chain_verified':True}))
"""
def main():
 if os.geteuid()!=0:raise RuntimeError('sudo required')
 if call([DOCKER,'inspect','--format','{{.Image}}','mosquitto']).strip()!=IMAGE:
  raise RuntimeError('operating image drift')
 expected='dedbac762b24a73c91af719eb0a6611f41e177d75b63b20e6949cafe5e216df0'
 current=STATE/'current.json'
 if current.exists():expected=json.loads(current.read_text())['current_config_sha256']
 active_config=CONFIG/'mosquitto.conf'
 if current.exists():active_config=Path(json.loads(current.read_text())['active_config_file'])
 if hashlib.sha256(active_config.read_bytes()).hexdigest()!=expected:
  raise RuntimeError('operating broker config drift')
 profile=json.loads((BASE/'inventory.json').read_text())
 credentials=json.loads((BASE/'credentials-new.json').read_text())
 required=[*profile['targets'],profile['ha_username'],*profile['diagnostic_usernames'],*profile['smartbox'].values()]
 if len(set(required+[profile['backend_username']]))!=len(required)+1 or set(credentials)!=set(required):
  raise RuntimeError('credential principal inventory mismatch')
 for name,value in credentials.items():
  if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',name) or not re.fullmatch(r'[a-f0-9]{64}',value):
   raise RuntimeError('invalid staged credential')
 password=(VAULT/'mqtt_password').read_text().strip()
 if not password or any(x in password for x in ['\n','\r','\0']):raise RuntimeError('invalid Backend password file')
 credentials[profile['backend_username']]=password
 runtime={}
 for line in Path('/volume1/docker/smart-gatekeeper-backend/runtime.env').read_text().splitlines():
  if line and not line.startswith('#') and '=' in line:
   key,value=line.split('=',1);runtime[key]=value
 if runtime.get('MQTT_USER')!=profile['backend_username'] or runtime.get('COMMAND_TARGET_ID') not in profile['targets']:
  raise RuntimeError('operating Backend identity drift')
 base=Path('/volume1/smart-gatekeeper-broker-private')
 if base.is_symlink() or base.stat().st_uid!=0 or stat.S_IMODE(base.stat().st_mode)!=0o700:
  raise RuntimeError('unsafe private staging parent')
 stage=base/('migration-'+uuid.uuid4().hex);stage.mkdir(mode=0o700)
 backup=stage/'original';backup.mkdir(mode=0o700)
 originals={}
 collector_config=Path('/volume1/docker/telegraf/telegraf.conf')
 if current.exists():collector_config=Path(json.loads(current.read_text())['collector_config_file'])
 for index,path in enumerate([active_config,CONFIG/'cert.pem',CONFIG/'chain.pem',CONFIG/'privkey.pem',
    collector_config,
    Path('/volume1/docker/homeassistant/.storage/core.config_entries')]):
  dest=backup/('file-'+str(index));shutil.copyfile(str(path),str(dest));os.chmod(str(dest),0o600)
  originals[str(path)]={**metadata(path),'backup':str(dest)}
 policy=stage/'policy';policy.mkdir(mode=0o750)
 top=call([DOCKER,'top','mosquitto','-eo','pid,uid,gid,comm'])
 rows=[line.split() for line in top.splitlines()[1:] if line.split()[-1:] == ['mosquitto']]
 if len(rows)!=1:raise RuntimeError('broker runtime UID not uniquely identified')
 uid,gid=int(rows[0][1]),int(rows[0][2])
 os.chown(str(policy),0,gid)
 write(policy/'credentials.json',json.dumps(credentials))
 write(policy/'inventory.json',json.dumps(profile))
 write(policy/'passwords',''.join(name+':'+value+'\n' for name,value in credentials.items()))
 write(policy/'acl',(BASE/'acl.candidate').read_text())
 call([DOCKER,'run','--rm','--network','none','--user','0:0','-v',str(policy)+':/policy',
       '--entrypoint','mosquitto_passwd',IMAGE,'-U','/policy/passwords'])
 for leaf in ['cert.pem','chain.pem','privkey.pem']:
  shutil.copyfile(str(CONFIG/leaf),str(policy/leaf));os.chmod(str(policy/leaf),0o600)
 config='per_listener_settings false\nallow_anonymous false\npassword_file /policy/passwords\nacl_file /policy/acl\npersistence false\nlog_dest stdout\nlog_type error\nlistener 1883 0.0.0.0\nlistener 8883 0.0.0.0\ncertfile /policy/cert.pem\ncafile /policy/chain.pem\nkeyfile /policy/privkey.pem\n'
 write(policy/'mosquitto.conf',config)
 for leaf in ['passwords','acl','cert.pem','chain.pem','privkey.pem','mosquitto.conf']:
  os.chown(str(policy/leaf),uid,gid)
 name='sgk-policy-stage-'+uuid.uuid4().hex[:12]
 started=False
 try:
  call([DOCKER,'run','--rm','-d','--name',name,'--user',str(uid)+':'+str(gid),
       '-p','127.0.0.1::1883','-p','127.0.0.1::8883','-v',str(policy)+':/policy:ro',
       '--entrypoint','mosquitto',IMAGE,'-c','/policy/mosquitto.conf'])
  started=True;ports={}
  for role,containerport in [('plain','1883/tcp'),('tls','8883/tcp')]:
   bound=call([DOCKER,'port',name,containerport]).strip()
   host,port=bound.rsplit(':',1)
   if host!='127.0.0.1' or not port.isdecimal():raise RuntimeError('fixture must bind only loopback')
   ports[role]=int(port)
  write(policy/'probe.json',json.dumps({'hostname':runtime['MQTT_HOST'],'ports':ports}))
  backend_image=call([DOCKER,'inspect','--format','{{.Image}}','smart-gatekeeper-production-api-1']).strip()
  output=call([DOCKER,'run','--rm','-i','--read-only','--network','host','--user','0:0',
      '-v',str(policy)+':/policy:ro','-v',str(VAULT/'mqtt_ca.pem')+':/client-ca.pem:ro',
      '--entrypoint','python3',backend_image,'-B','-I','-'],input=SDK.encode(),timeout=100)
  validation=json.loads(output)
  if validation['isolated_auth_cases']!=16:raise RuntimeError('authentication matrix incomplete')
 finally:
  if started:call([DOCKER,'rm','-f',name])
 result={'schema_version':1,'captured_at_utc':datetime.now(timezone.utc).isoformat(),
    'broker_operating_configuration_changed':False,'new_credentials_installed':False,
    'stage_root':str(stage),'policy_root':str(policy),'broker_uid':uid,'broker_gid':gid,
    'originals':originals,'validation':validation,'files':{leaf:metadata(policy/leaf) for leaf in ['acl','passwords','mosquitto.conf']}}
 report(result,'evidence')
 return result
if __name__=='__main__':
 try:main()
 except Exception as error:
  report({'error_type':type(error).__name__,'message':str(error),'failed_query':LAST_ERROR},'error')
  print('private_candidate_stage_failed=true; private_error_report_saved=true')
  raise SystemExit(1)
