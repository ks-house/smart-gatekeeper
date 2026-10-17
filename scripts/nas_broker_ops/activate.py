"""Bounded broker/collector replacement with retained stopped-container rollback."""
from pathlib import Path
import copy
import hashlib
import http.client
import json
import os
import re
import socket
import sqlite3
import ssl
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import uuid

OPS=Path("/usr/local/lib/smart-gatekeeper-broker-ops")
STATE=OPS/"state"
INCOMING=OPS/"incoming"
PRIVATE=Path("/volume1/smart-gatekeeper-broker-private")
DOCKER="/usr/local/bin/docker"
SOCKET="/var/run/docker.sock"
NAMES={"mosquitto","telegraf"}
NAS_SELF_HOST="tworimpa.synology.me"
NAS_SELF_HTTPS_PORTS=(4123,4442)
DOCKER_LOG_ROOT=Path("/volume1/@docker/containers")


def atomic(path, text, uid=0, gid=0, mode=0o600):
    fd,name=tempfile.mkstemp(prefix=".candidate-",dir=str(path.parent))
    try:
        os.fchmod(fd,mode);os.fchown(fd,uid,gid)
        with os.fdopen(fd,"w") as stream:
            stream.write(text);stream.flush();os.fsync(stream.fileno())
        os.replace(name,str(path))
    finally:
        if os.path.exists(name):os.unlink(name)


class DockerHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout);self.sock.connect(SOCKET)


def api(method,path,data=None):
    connection=DockerHTTP("localhost",timeout=30)
    body=json.dumps(data).encode() if data is not None else None
    connection.request(method,path,body,{"Content-Type":"application/json"})
    response=connection.getresponse();raw=response.read(4*1024*1024+1)
    status=response.status;connection.close()
    if len(raw)>4*1024*1024:raise RuntimeError("Docker response bound")
    if status>=300:
        # Do not echo cloned container environments or credential-bearing config.
        raise RuntimeError("bounded Docker operation failed: HTTP"+str(status))
    return json.loads(raw) if raw else {}


def inspect(name):
    return api("GET","/containers/"+urllib.parse.quote(name,safe="")+"/json")


def copy_create_payload(original,overrides):
    config=copy.deepcopy(original["Config"])
    config["Image"]=original["Image"]  # Exact installed image, no latest resolution.
    host=copy.deepcopy(original["HostConfig"])
    binds=[]
    for item in host.get("Binds") or []:
        parts=item.split(":")
        if len(parts)<2:raise RuntimeError("unexpected existing bind")
        if parts[1] not in overrides:binds.append(item)
    host["Mounts"]=[item for item in host.get("Mounts") or []
                    if item.get("Target") not in overrides]
    for destination,source in overrides.items():
        resolved=Path(source).resolve(strict=True)
        if PRIVATE not in resolved.parents:raise ValueError("replacement mount must be private")
        binds.append(str(resolved)+":"+destination+":ro")
    host["Binds"]=binds;config["HostConfig"]=host
    endpoints={}
    for network,item in original.get("NetworkSettings",{}).get("Networks",{}).items():
        endpoints[network]={key:copy.deepcopy(item[key]) for key in
                            ("IPAMConfig","Links","Aliases","DriverOpts")
                            if item.get(key) is not None}
    if any(item.get("IPAMConfig",{}).get("IPv4Address") or
           item.get("IPAMConfig",{}).get("IPv6Address") for item in endpoints.values()):
        raise ValueError("static container addresses require a separate recovery plan")
    if endpoints:config["NetworkingConfig"]={"EndpointsConfig":endpoints}
    return config


def preserve_replacement_diagnostics(name,original_id):
    """Collect only a replacement's bounded private evidence before rollback."""
    try:
        current=inspect(name)
        if current["Id"]==original_id:return
        directory=Path(tempfile.mkdtemp(prefix="activation-diagnostic-",dir=str(STATE)))
        os.chmod(directory,0o700)
        value={"name":name,"container_id":current["Id"],"image":current["Image"],
               "state":current["State"],"restart_count":current.get("RestartCount",0),
               "logging":current["HostConfig"].get("LogConfig"),"log_records":[]}
        if current["HostConfig"].get("LogConfig",{}).get("Type")=="db":
            identifier=current["Id"]
            if re.fullmatch(r"[a-f0-9]{64}",identifier) is None:
                raise ValueError("bound failed container identity required")
            path=DOCKER_LOG_ROOT/identifier/"log.db"
            if path.is_file() and not path.is_symlink() and path.stat().st_uid==0:
                connection=sqlite3.connect("file:"+str(path)+"?mode=ro",uri=True,timeout=2)
                try:
                    connection.execute("PRAGMA query_only=ON")
                    deadline=time.monotonic()+2
                    connection.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
                    value["log_records"]=connection.execute(
                        "SELECT c2created,substr(c0text,1,1000) FROM log_content ORDER BY docid DESC LIMIT 200").fetchall()
                finally:connection.close()
        atomic(directory/"container.json",json.dumps(value))
        atomic(STATE/"last-activation-diagnostic.json",json.dumps(
            {"private_directory":str(directory),"name":name,"container_id":current["Id"]}))
    except Exception as error:
        # Evidence failure must not prevent restoring the original service.
        try:atomic(STATE/"last-activation-diagnostic-error.json",json.dumps({"error_type":type(error).__name__}))
        except Exception:pass


def wait_broker_principal(profile,credentials,endpoint=("127.0.0.1",1883)):
    username=profile["ha_username"];password=credentials[username]
    def field(value):
        raw=value.encode()
        return len(raw).to_bytes(2,"big")+raw
    body=(field("MQTT")+bytes([5,194,0,10,0])+field("sgk-activation-"+uuid.uuid4().hex[:12])
          +field(username)+field(password))
    remaining=len(body);encoded=bytearray()
    while True:
        digit=remaining%128;remaining//=128;encoded.append(digit|(128 if remaining else 0))
        if not remaining:break
    packet=bytes([16])+bytes(encoded)+body
    until=time.monotonic()+30
    while True:
        try:
            with socket.create_connection(endpoint,timeout=1) as stream:
                stream.settimeout(2);stream.sendall(packet)
                def exact(count):
                    value=b""
                    while len(value)<count:
                        part=stream.recv(count-len(value))
                        if not part:raise RuntimeError("bounded MQTT ready response closed")
                        value+=part
                    return value
                if exact(1)!=bytes([32]):raise RuntimeError("MQTT ready CONNACK required")
                length=0;multiplier=1
                for index in range(4):
                    digit=exact(1)[0];length+=(digit&127)*multiplier
                    if not digit&128:break
                    multiplier*=128
                else:raise RuntimeError("bounded MQTT ready response required")
                if not 3<=length<=256:raise RuntimeError("bounded MQTT ready response required")
                reply=exact(length)
                if reply[0]!=0 or reply[1]!=0:
                    raise RuntimeError("prepared principal was refused before collector start")
                stream.sendall(bytes([224,0]))
                return {"prepared_principal_connect_only_verified":True}
        except OSError:
            if time.monotonic()>=until:raise RuntimeError("bounded broker readiness deadline before collector")
            time.sleep(.25)


def replace_broker_and_collector(stage,active,client,profile,credentials,prepared):
    replace_container("mosquitto",{
        "/mosquitto/config/mosquitto.conf":str(active),"/mosquitto/auth":str(Path(stage["policy_root"]))},
        prepared,str(stage["broker_uid"])+":"+str(stage["broker_gid"]))
    readiness=wait_broker_principal(profile,credentials)
    replace_container("telegraf",{"/etc/telegraf/telegraf.conf":str(client)},prepared)
    return readiness


def restore_transaction(items):
    # Both forward activation and rollback require the broker before its consumer.
    for item in sorted(items,key=lambda item:0 if item["original"]=="mosquitto" else 1):
        restore_container(item)


def replace_container(name,overrides,prepared=None,runtime_user=None):
    if name not in NAMES:raise ValueError("unsupported operating container")
    original=inspect(name);payload=copy_create_payload(original,overrides)
    if runtime_user is not None:
        if name!="mosquitto" or re.fullmatch(r"[0-9]+:[0-9]+",runtime_user) is None:
            raise ValueError("invalid explicit broker runtime user")
        payload["User"]=runtime_user
    backup=name+"_sgk_previous_"+uuid.uuid4().hex[:10]
    restart=original["HostConfig"].get("RestartPolicy",{"Name":"no"})
    item={"original":name,"backup":backup,"restart_policy":restart,
          "original_image":original["Image"],"original_id":original["Id"]}
    if prepared is not None:prepared(item)
    api("POST","/containers/"+name+"/stop?t=15")
    try:
        api("POST","/containers/"+name+"/update",
            {"RestartPolicy":{"Name":"no","MaximumRetryCount":0}})
        api("POST","/containers/"+name+"/rename?name="+backup)
        try:
            api("POST","/containers/create?name="+name,payload)
            api("POST","/containers/"+name+"/start")
        except Exception:
            preserve_replacement_diagnostics(name,original["Id"])
            try:api("DELETE","/containers/"+name+"?force=true")
            except Exception:pass
            api("POST","/containers/"+backup+"/rename?name="+name)
            api("POST","/containers/"+name+"/update",{"RestartPolicy":restart})
            api("POST","/containers/"+name+"/start")
            raise
    except Exception:
        # If rename never happened, restore the original unit directly.
        try:
            current=inspect(name)
            if current["Id"]==original["Id"]:
                api("POST","/containers/"+name+"/update",{"RestartPolicy":restart})
                api("POST","/containers/"+name+"/start")
        except Exception:pass
        raise
    return item


def restore_container(item):
    name=item["original"];backup=item["backup"]
    if name not in NAMES or not re.fullmatch(re.escape(name)+r"_sgk_previous_[a-f0-9]{10}",backup):
        raise ValueError("invalid retained rollback unit")
    try:
        old=inspect(backup)
    except RuntimeError as error:
        if "HTTP404" not in str(error):raise
        current=inspect(name)
        if current["Id"]!=item["original_id"] or current["Image"]!=item["original_image"]:
            raise RuntimeError("unrecognized rollback unit")
        api("POST","/containers/"+name+"/update",{"RestartPolicy":item["restart_policy"]})
        if current["State"]["Status"]!="running":api("POST","/containers/"+name+"/start")
        return
    if old["Id"]!=item["original_id"] or old["Image"]!=item["original_image"]:
        raise RuntimeError("retained rollback identity drift")
    preserve_replacement_diagnostics(name,item["original_id"])
    try:api("DELETE","/containers/"+name+"?force=true")
    except RuntimeError:
        # Proceed only if the replacement is already absent.
        try:inspect(name)
        except RuntimeError:pass
        else:raise
    api("POST","/containers/"+backup+"/rename?name="+name)
    api("POST","/containers/"+name+"/update",{"RestartPolicy":item["restart_policy"]})
    api("POST","/containers/"+name+"/start")


def collector_config(text,username,password):
    match=re.search(r"(?ms)^(\s*\[\[inputs\.mqtt_consumer\]\]\s*\n)(.*?)(?=^\s*\[\[|\Z)",text)
    if match is None or len(re.findall(r"(?m)^\s*\[\[inputs\.mqtt_consumer\]\]",text))!=1:
        raise ValueError("one exact MQTT collector required")
    body=re.sub(r"(?m)^\s*(?:username|password|client_id)\s*=.*\n?","",match.group(2))
    replacement=(match.group(1)+"  username = "+json.dumps(username)+"\n  password = "+
        json.dumps(password)+"\n  client_id = \"smartbox-telegraf\"\n"+body)
    return text[:match.start()]+replacement+text[match.end():]


SDK=r"""
from pathlib import Path
import json,socket,ssl,threading,time,uuid
import paho.mqtt.client as mqtt
p=json.loads(Path('/policy/observe.json').read_text())
creds=json.loads(Path('/policy/credentials.json').read_text())
profile=json.loads(Path('/policy/inventory.json').read_text())
host=p['hostname'];port=p['port'];saved=socket.getaddrinfo
def resolve(h,q,*args,**kwargs):
 return saved('127.0.0.1' if h==host and int(q)==port else h,q,*args,**kwargs)
socket.getaddrinfo=resolve
client=mqtt.Client(client_id='maintenance-read-'+uuid.uuid4().hex[:12],clean_session=True)
client.username_pw_set(profile['ha_username'],creds[profile['ha_username']])
client.tls_set_context(ssl.create_default_context(cafile='/client-ca.pem'))
done=threading.Event();values={};fresh=set()
topics={'gatekeeper/v1/targets/'+p['target_id']+'/status':'target',
        'smartbox/status':'box-status','smartbox/telemetry':'box-telemetry'}
def connected(c,u,f,rc):
 if rc!=0:values['connection_rejected']=True;done.set();return
 c.subscribe([(topic,1) for topic in topics])
def message(c,u,m):
 if len(m.payload)>32768:return
 try:d=json.loads(m.payload)
 except Exception:return
 key=topics.get(m.topic)
 if key is None or not isinstance(d,dict):return
 if key=='target':values['target_version']=d.get('firmware');values['target_state']=d.get('fsm_state',d.get('state'));values['target_relay']=d.get('relay_commanded_on')
 elif key=='box-status':values['smartbox_version']=d.get('firmware_version')
 else:values['smartbox_state']=d.get('fsm_state')
 if not m.retain:fresh.add(key)
 if {'target','box-telemetry'}<=fresh and 'smartbox_version' in values:done.set()
client.on_connect=connected;client.on_message=message
client.connect(host,port,keepalive=15);client.loop_start()
try:
 if not done.wait(75):raise RuntimeError('fresh device evidence deadline')
 if values.get('target_version')!=p['versions']['target'] or values.get('smartbox_version')!=p['versions']['smartbox']:
  raise RuntimeError('installed device versions do not match candidate')
 if p['require_idle'] and (values.get('target_state') not in ('IDLE',0) or values.get('smartbox_state')!='IDLE' or values.get('target_relay') is not False):
  raise RuntimeError('device maintenance window is not idle')
 print(json.dumps({'matching_versions':True,'fresh_target':True,'fresh_smartbox_telemetry':True,'idle_preflight':p['require_idle']}))
finally:client.disconnect();client.loop_stop()
"""


def observe(stage,versions,require_idle):
    runtime={}
    for line in Path("/volume1/docker/smart-gatekeeper-backend/runtime.env").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key,value=line.split("=",1);runtime[key]=value
    policy=Path(stage["policy_root"])
    atomic(policy/"observe.json",json.dumps({"hostname":runtime["MQTT_HOST"],
           "port":int(runtime["MQTT_PORT"]),"target_id":runtime["COMMAND_TARGET_ID"],
           "versions":versions,"require_idle":require_idle}))
    image=inspect("smart-gatekeeper-production-api-1")["Image"]
    result=subprocess.run([DOCKER,"run","--rm","-i","--read-only","--network","host","--user","0:0",
        "-v",str(policy)+":/policy:ro",
        "-v","/volume1/docker/smart-gatekeeper-backend/secrets/mqtt_ca.pem:/client-ca.pem:ro",
        "--entrypoint","python3",image,"-B","-I","-"],input=SDK.encode(),
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=95)
    if result.returncode:
        atomic(STATE/"last-observe-error.json",json.dumps(
            {"stderr":result.stderr.decode("utf-8","replace")[-4000:]}))
        raise RuntimeError("fresh installed device preflight/readback failed")
    return json.loads(result.stdout)


class LocalNASHTTPS(http.client.HTTPSConnection):
    """Keep the public certificate/SNI/Host identity on the local NAS route."""
    def connect(self):
        self.sock=socket.create_connection(("127.0.0.1",self.port),timeout=self.timeout)
        self.sock=self._context.wrap_socket(self.sock,server_hostname=self.host)


def https_response(url,limit=1048576):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!="https" or parsed.username is not None or parsed.password is not None:
        raise ValueError("verified HTTPS origin required")
    context=ssl.create_default_context()
    if parsed.hostname==NAS_SELF_HOST and parsed.port in NAS_SELF_HTTPS_PORTS:
        connection=LocalNASHTTPS(parsed.hostname,parsed.port,timeout=8,context=context)
        try:
            target=parsed.path or "/"
            if parsed.query:target+="?"+parsed.query
            connection.request("GET",target,headers={"Host":parsed.netloc})
            response=connection.getresponse();raw=response.read(limit+1)
            status=response.status
        finally:
            connection.close()
    else:
        request=urllib.request.Request(url,method="GET")
        with urllib.request.urlopen(request,timeout=8,context=context) as response:
            status=response.status;raw=response.read(limit+1)
    if len(raw)>limit:
        raise RuntimeError("bounded HTTPS response required")
    return status,raw


def ready():
    configuration=json.loads((OPS/"config.json").read_text())
    url=configuration["readiness_url"]
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!="https" or parsed.username is not None or parsed.path!="/ready" or parsed.query:
        raise ValueError("invalid fixed readiness route")
    status,raw=https_response(url)
    if status!=200:raise RuntimeError("independent readiness HTTP did not pass")
    data=json.loads(raw)
    if data.get("status") not in ("ready","ok") or not all(data.get("checks",{}).values()):
        raise RuntimeError("independent readiness did not pass")
    return {"readiness_passed":True,"build_sha":data.get("build_sha")}


def activate():
    stage=json.loads((STATE/"stage-evidence.json").read_text())
    expected=json.loads((INCOMING/"expected.json").read_text())
    if expected is None:raise ValueError("installed device versions must be supplied before activation")
    source_hash=hashlib.sha256(b"\0".join((INCOMING/name).read_bytes() for name in
                              ("inventory.json","credentials-new.json","acl.candidate","expected.json"))).hexdigest()
    if stage["input_sha256"]!=source_hash or stage["validation"]["isolated_auth_cases"]!=16:
        raise ValueError("matching successful private candidate required")
    previous=json.loads((STATE/"current.json").read_text()) if (STATE/"current.json").exists() else None
    source=Path(previous["active_config_file"]) if previous else Path("/volume1/docker/mosquitto/config/mosquitto.conf")
    expected_hash=previous["current_config_sha256"] if previous else stage["originals"][str(source)]["sha256"]
    if hashlib.sha256(source.read_bytes()).hexdigest()!=expected_hash:raise RuntimeError("operating config drift")
    configuration=json.loads((OPS/"config.json").read_text())
    for path,digest in configuration["origin_guard_hashes"].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=digest:raise RuntimeError("origin guard drift")
    observe(stage,expected,True);ready()
    policy=Path(stage["policy_root"]);profile=json.loads((policy/"inventory.json").read_text())
    credentials=json.loads((policy/"credentials.json").read_text())
    new=source.read_text()
    if re.search(r"(?m)^\s*(include_dir|plugin|auth_plugin)\s",new):raise ValueError("unreviewed broker plugin/include")
    if len(re.findall(r"(?m)^\s*listener\s",new))!=2:raise ValueError("unexpected listener inventory")
    new=re.sub(r"(?m)^\s*(?:password_file|acl_file|per_listener_settings)\s+.*\n?","",new)
    new,count=re.subn(r"(?m)^(\s*allow_anonymous\s+)(true|false)\s*$",r"\1false",new)
    if count!=2:raise ValueError("explicit policy required on both listeners")
    new="per_listener_settings false\npassword_file /mosquitto/auth/passwords\nacl_file /mosquitto/auth/acl\n"+new
    active=Path(stage["stage_root"])/"active-mosquitto.conf"
    atomic(active,new,stage["broker_uid"],stage["broker_gid"])
    collector=inspect("telegraf")
    mounts=[item for item in collector["Mounts"] if item["Destination"]=="/etc/telegraf/telegraf.conf"]
    if len(mounts)!=1:raise ValueError("collector mount drift")
    text=Path(mounts[0]["Source"]).read_text()
    client=Path(stage["stage_root"])/"active-telegraf.conf"
    text=collector_config(text,profile["smartbox"]["telemetry_username"],
                          credentials[profile["smartbox"]["telemetry_username"]])
    top=subprocess.run([DOCKER,"top","telegraf","-eo","pid,uid,gid,comm"],
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15)
    rows=[line.split() for line in top.stdout.decode().splitlines()[1:]
          if line.split()[-1:]==["telegraf"]]
    if top.returncode or len(rows)!=1:raise RuntimeError("collector runtime UID not identified")
    atomic(client,text,int(rows[0][1]),int(rows[0][2]))
    replaced=[]
    transaction={"containers":replaced,"stage_root":stage["stage_root"],"previous_state":previous}
    atomic(STATE/"pending.json",json.dumps(transaction))
    def prepared(item):
        replaced.append(item)
        atomic(STATE/"pending.json",json.dumps(transaction))
    try:
        broker_readiness=replace_broker_and_collector(stage,active,client,profile,credentials,prepared)
        observe(stage,expected,False);health=ready()
        collector_state=inspect("telegraf")
        if collector_state["State"]["Status"]!="running" or collector_state.get("RestartCount",0):
            raise RuntimeError("collector did not remain running after reconnect")
        current={**transaction,"current_config_sha256":hashlib.sha256(active.read_bytes()).hexdigest(),
                 "active_config_file":str(active),"collector_config_file":str(client),
                 "device_versions":expected,"authenticated_policy_installed":True,
                 "old_sessions_evicted":True,"ha_client_reconnect_verified":False}
        atomic(STATE/"current.json",json.dumps(current))
        (STATE/"pending.json").unlink()
        return {"authenticated_policy_installed":True,"old_sessions_evicted":True,**health,
                **broker_readiness,"ha_client_reconnect_verified":False}
    except Exception:
        restore_transaction(replaced)
        if (STATE/"pending.json").exists():(STATE/"pending.json").unlink()
        raise


def rollback():
    path=STATE/"current.json"
    pending=STATE/"pending.json"
    if not path.exists() and not pending.exists():raise ValueError("no activation to restore")
    current=json.loads((pending if pending.exists() else path).read_text())
    restore_transaction(current["containers"])
    previous=current["previous_state"]
    if previous is None:
        if path.exists():path.unlink()
    else:atomic(path,json.dumps(previous))
    if pending.exists():pending.unlink()
    return {"rollback_restored":True,**ready()}
