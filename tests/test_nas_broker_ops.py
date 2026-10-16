"""Closed NAS inputs, forced-command boundary and isolated container rollback."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid
ROOT=Path(__file__).resolve().parents[1]
OPS=ROOT/"scripts/nas_broker_ops"
IMAGE="eclipse-mosquitto@sha256:6f8d8a947c506f8a2290ec65cd4bd2bc7cb4d43fb5f6271f861cb013e2ef9797"
PROFILE={"schema_version":2,"targets":["target-a"],"backend_username":"backend",
 "ha_username":"ha","diagnostic_usernames":["diag"],"discovery_device_id":"gatekeeper",
 "smartbox":{"device_username":"box","telemetry_username":"collector"}}
def module(name):
 spec=importlib.util.spec_from_file_location("nas_test_"+name,OPS/(name+".py"))
 result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
def bundle():
 return {"schema_version":1,"inventory":copy.deepcopy(PROFILE),"expected_versions":None,
         "credentials":{name:"a"*64 for name in ["target-a","ha","diag","box","collector"]}}
class NasGatewayInputTest(unittest.TestCase):
 def setUp(self):
  from scripts import render_broker_acl
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.gateway=module("broker_ops")
  self.gateway.INCOMING=self.root/"incoming"
  self.gateway.STATE=self.root/"state";self.gateway.STATE.mkdir()
  self.gateway.RUNTIME=self.root/"runtime.env"
  self.gateway.RUNTIME.write_text("MQTT_USER=backend\nCOMMAND_TARGET_ID=target-a\n")
  self.gateway.load_module=lambda name:render_broker_acl
 def tearDown(self):self.temp.cleanup()
 def receive(self,value):return self.gateway.receive(json.dumps(value).encode())
 def test_valid_private_receive_keeps_runtime_untouched(self):
  original=self.gateway.RUNTIME.read_bytes();result=self.receive(bundle())
  self.assertTrue(result["received"]);self.assertFalse(result["operating_broker_changed"])
  self.assertEqual(original,self.gateway.RUNTIME.read_bytes())
  for path in self.gateway.INCOMING.iterdir():self.assertEqual(0o600,path.stat().st_mode & 0o777)
  self.assertNotIn("a"*64,(self.gateway.INCOMING/"acl.candidate").read_text())
 def test_invalid_input_fails_before_any_write(self):
  cases=[]
  value=bundle();value["path"]="/etc/sudoers";cases.append(value)
  value=bundle();value["inventory"]["backend_username"]="other";cases.append(value)
  value=bundle();value["inventory"]["targets"]=["other"];cases.append(value)
  value=bundle();value["credentials"]["box"]="bad\npassword";cases.append(value)
  value=bundle();value["inventory"]["smartbox"]["device_username"]="box;id";cases.append(value)
  value=bundle();value["expected_versions"]={"target":"x"};cases.append(value)
  value=bundle();value["inventory"]["discovery_device_id"]="smartbox_01";cases.append(value)
  for value in cases:
   with self.subTest(value=value),self.assertRaises(ValueError):self.receive(value)
   self.assertFalse(self.gateway.INCOMING.exists())
 def test_input_byte_bound(self):
  with self.assertRaises(ValueError):self.gateway.receive(b"x"*(self.gateway.MAX_INPUT+1))
  self.assertFalse(self.gateway.INCOMING.exists())
 def test_every_complete_bundle_change_invalidates_stage(self):
  value=bundle();self.receive(value)
  evidence=self.gateway.STATE/"stage-evidence.json";evidence.write_text("{}")
  value["expected_versions"]={"target":"2.1.515+main.gabc","smartbox":"0.1.0-gabc"}
  self.receive(value);self.assertFalse(evidence.exists())
  evidence.write_text("{}")
  value["credentials"]["diag"]="b"*64;self.receive(value);self.assertFalse(evidence.exists())
 def test_interrupted_bundle_write_keeps_previous_complete_input(self):
  value=bundle();self.receive(value)
  before=self.gateway.INCOMING.resolve()
  snapshot={path.name:path.read_bytes() for path in self.gateway.INCOMING.iterdir()}
  original=self.gateway.atomic
  def fail_at_acl(path,content,*args,**kwargs):
   if path.name=="acl.candidate":raise OSError("synthetic interrupted write")
   return original(path,content,*args,**kwargs)
  self.gateway.atomic=fail_at_acl
  value["inventory"]["discovery_device_id"]="different"
  with self.assertRaises(OSError):self.receive(value)
  self.assertEqual(before,self.gateway.INCOMING.resolve())
  self.assertEqual(snapshot,{path.name:path.read_bytes() for path in self.gateway.INCOMING.iterdir()})
 def test_validated_digest_includes_acl_and_expected_version(self):
  self.receive(bundle());first=self.gateway.input_hash()
  (self.gateway.INCOMING/"acl.candidate").write_text("synthetic changed policy")
  self.assertNotEqual(first,self.gateway.input_hash())
  self.receive(bundle());first=self.gateway.input_hash()
  (self.gateway.INCOMING/"expected.json").write_text('{"target":"changed"}')
  self.assertNotEqual(first,self.gateway.input_hash())
 def test_forced_dispatcher_rejects_shell_injection(self):
  marker=self.root/"not-created"
  for command in ["id","sh","status; touch "+str(marker),"status\nid","receive $(id)",
                  "internal-sftp","scp -t /tmp/test",""]:
   result=subprocess.run(["sh",str(OPS/"ssh_dispatch.sh")],
       env={**os.environ,"SSH_ORIGINAL_COMMAND":command},capture_output=True,text=True)
   self.assertEqual(126,result.returncode,command);self.assertFalse(marker.exists())
 def test_collector_change_preserves_complete_output_and_topic_configuration(self):
  activate=module("activate")
  original=('[['+'inputs.mqtt_consumer]]\n'
    '  servers = ["tcp://example.test:1883"]\n'
    '  topics = ["smartbox/telemetry", "smartbox/event/#"]\n'
    '  username = "old"\n  password = "old"\n'
    '[[outputs.influxdb]]\n  token = "fixture-influx-token"\n')
  changed=activate.collector_config(original,"collector","b"*64)
  self.assertEqual(original.split("[[outputs.influxdb]]")[1],
                   changed.split("[[outputs.influxdb]]")[1])
  self.assertIn('topics = ["smartbox/telemetry", "smartbox/event/#"]',changed)
  self.assertIn('username = "collector"',changed);self.assertNotIn('password = "old"',changed)
 def test_embedded_sdk_workers_compile_without_running_device_actions(self):
  for name in ("stage","activate"):
   compile(module(name).SDK,name+"-worker","exec")
 def test_private_mount_boundary(self):
  activate=module("activate");activate.PRIVATE=self.root/"private";activate.PRIVATE.mkdir()
  source=self.root/"outside";source.write_text("fixture")
  original={"Config":{},"HostConfig":{},"Image":"fixture","NetworkSettings":{}}
  with self.assertRaises(ValueError):activate.copy_create_payload(original,{"/config":str(source)})
class NasSetupCaptureTest(unittest.TestCase):
 def test_synology_proxy_source_accepts_only_tailnet_and_exact_loopback(self):
  import ipaddress
  bootstrap=module("bootstrap")
  networks=[ipaddress.ip_network(value) for value in bootstrap.SSH_SOURCE_RANGES]
  for address,expected in [("100.95.243.92",True),("127.0.0.1",True),
                           ("127.0.0.2",False),("192.168.55.10",False),
                           ("203.0.113.10",False),("::1",False)]:
   with self.subTest(address=address):
    self.assertEqual(expected,any(ipaddress.ip_address(address) in net for net in networks))
  line=bootstrap.restricted_key_line("ssh-ed25519 AAAA fixture").decode()
  self.assertIn('restrict,from="100.64.0.0/10,127.0.0.1",command="',line)
  self.assertIn(str(bootstrap.ROOT/"bin/ssh_dispatch.sh"),line)
 def test_package_bytes_cannot_change_after_validation(self):
  bootstrap=module("bootstrap")
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   names=set(bootstrap.DESTINATIONS)|{"initial-input.json","config.json","broker-key.pub"}
   originals={name:("original-"+name).encode() for name in names}
   for name,data in originals.items():(root/name).write_bytes(data)
   manifest={name:hashlib.sha256(data).hexdigest() for name,data in originals.items()}
   raw=json.dumps(manifest).encode();(root/"manifest.json").write_bytes(raw)
   approved,captured=bootstrap.capture_package(root,hashlib.sha256(raw).hexdigest())
   (root/"broker_ops.py").write_bytes(b"substituted-untrusted-code")
   self.assertEqual(originals["broker_ops.py"],captured["broker_ops.py"])
   self.assertEqual(manifest,approved)
 def test_manifest_substitution_is_rejected(self):
  bootstrap=module("bootstrap")
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/"manifest.json").write_text("{}")
   with self.assertRaises(ValueError):bootstrap.capture_package(root,"0"*64)

@unittest.skipUnless(os.getenv("RUN_NAS_BROKER_OPS_INTEGRATION")=="1",
                     "set RUN_NAS_BROKER_OPS_INTEGRATION=1 for local Docker rollback")
class NasContainerRollbackIntegrationTest(unittest.TestCase):
 def test_private_replacement_and_retained_unit_rollback(self):
  activate=module("activate")
  with tempfile.TemporaryDirectory(prefix="nas-ops-rollback-") as tmp:
   root=Path(tmp);activate.PRIVATE=root
   old=root/"old.conf";old.write_text("old-fixture")
   new=root/"new.conf";new.write_text("new-fixture")
   name="sgk-ops-fixture-"+uuid.uuid4().hex[:10];activate.NAMES={name};item=None
   def docker(*args):
    result=subprocess.run(["docker",*args],capture_output=True,text=True,timeout=30)
    if result.returncode:raise RuntimeError(result.stderr[-1000:])
    return result.stdout
   try:
    docker("run","-d","--name",name,"--network","none","--restart","unless-stopped",
     "--user",str(os.getuid())+":"+str(os.getgid()),"-e","MIGRATION_MARKER=preserve",
     "-v",str(old)+":/fixture.conf:ro","--entrypoint","sh",IMAGE,"-c","exec sleep 300")
    item=activate.replace_container(name,{"/fixture.conf":str(new)})
    self.assertEqual("new-fixture",docker("exec",name,"cat","/fixture.conf").strip())
    self.assertEqual("no",activate.inspect(item["backup"])["HostConfig"]["RestartPolicy"]["Name"])
    self.assertIn("MIGRATION_MARKER=preserve",activate.inspect(name)["Config"]["Env"])
    self.assertEqual(item["original_image"],activate.inspect(name)["Image"])
    activate.restore_container(item);item=None
    self.assertEqual("old-fixture",docker("exec",name,"cat","/fixture.conf").strip())
    self.assertEqual("unless-stopped",activate.inspect(name)["HostConfig"]["RestartPolicy"]["Name"])
   finally:
    subprocess.run(["docker","rm","-f",name],capture_output=True,timeout=30)
    if item:subprocess.run(["docker","rm","-f",item["backup"]],capture_output=True,timeout=30)
if __name__=="__main__":unittest.main()
