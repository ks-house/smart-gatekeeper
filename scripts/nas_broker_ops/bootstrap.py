#!/usr/bin/python3
"""One-time root install of a dedicated forced SSH key and fixed sudo commands."""
from pathlib import Path
import hashlib
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import tempfile
import uuid

ROOT=Path("/usr/local/lib/smart-gatekeeper-broker-ops")
OWNER=None
COMMANDS=("status","receive","stage","apply","rollback","diagnose")
PROGRAM=ROOT/"bin/broker_ops.py"
DESTINATIONS={"broker_ops.py":ROOT/"bin/broker_ops.py",
 "ssh_dispatch.sh":ROOT/"bin/ssh_dispatch.sh","stage.py":ROOT/"lib/stage.py",
 "activate.py":ROOT/"lib/activate.py","render_broker_acl.py":ROOT/"lib/render_broker_acl.py",
 "target-acl":ROOT/"security/target-acl"}


def write(path,data,uid=0,gid=0,mode=0o600):
    fd,name=tempfile.mkstemp(prefix=".setup-",dir=str(path.parent))
    try:
        os.fchmod(fd,mode);os.fchown(fd,uid,gid)
        with os.fdopen(fd,"wb") as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(name,str(path))
    finally:
        if os.path.exists(name):os.unlink(name)


def run(arguments,**kwargs):
    result=subprocess.run(arguments,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30,**kwargs)
    if result.returncode:
        raise RuntimeError("setup validation failed: "+result.stderr.decode("utf-8","replace")[-2000:])
    return result


def install(package):
    if os.geteuid()!=0:raise RuntimeError("one-time administrator authentication required")
    manifest=json.loads((package/"manifest.json").read_text())
    expected=set(DESTINATIONS)|{"initial-input.json","config.json","broker-key.pub"}
    if set(manifest)!=expected:raise ValueError("unexpected setup manifest")
    for name,digest in manifest.items():
        path=package/name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError("setup source hash mismatch")
    global OWNER
    configuration=json.loads((package/"config.json").read_text())
    OWNER=configuration["owner"]
    if not isinstance(OWNER,str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,31}",OWNER) is None:
        raise ValueError("invalid operator name")
    user=pwd.getpwnam(OWNER)
    key=(package/"broker-key.pub").read_text().strip()
    if re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/=]+(?: [A-Za-z0-9_.-]+)?",key) is None:
        raise ValueError("invalid dedicated public key")
    marker={"owner":OWNER,"public_key_sha256":hashlib.sha256(key.encode()).hexdigest()}
    if ROOT.is_symlink():raise RuntimeError("gateway path cannot be a symlink")
    if ROOT.exists():
        if (ROOT/"state/setup.json").exists():
            raise RuntimeError("gateway is already installed; use its dedicated key")
        old=ROOT/"state/installing.json"
        if ROOT.stat().st_uid!=0 or not old.exists() or json.loads(old.read_text())!=marker:
            raise RuntimeError("unrelated/incomplete gateway directory")
    run(["/usr/bin/sudo","-n","-l","-U",OWNER])
    ROOT.mkdir(mode=0o755,exist_ok=True)
    for leaf in ("bin","lib","security"):
        (ROOT/leaf).mkdir(mode=0o755,exist_ok=True)
    for leaf in ("state","incoming"):
        (ROOT/leaf).mkdir(mode=0o700,exist_ok=True)
    write(ROOT/"state/installing.json",json.dumps(marker,sort_keys=True).encode())
    for name,destination in DESTINATIONS.items():
        data=(package/name).read_bytes()
        if destination.suffix==".py":compile(data,str(destination),"exec")
        write(destination,data,mode=0o755 if destination.parent.name=="bin" else 0o644)
    import importlib.util
    for name in ("stage","activate"):
        spec=importlib.util.spec_from_file_location("setup_"+name,ROOT/"lib"/(name+".py"))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        compile(module.SDK,name+"-embedded-worker","exec")
    write(ROOT/"config.json",(package/"config.json").read_bytes())
    receive=run(["/usr/bin/python3","-I",str(PROGRAM),"receive"],
                input=(package/"initial-input.json").read_bytes())
    if not json.loads(receive.stdout)["received"]:raise RuntimeError("private input not accepted")

    def demote():
        os.initgroups(OWNER,user.pw_gid);os.setgid(user.pw_gid);os.setuid(user.pw_uid)
    protected=[ROOT.parent.parent,ROOT.parent,ROOT,ROOT/"bin",ROOT/"lib",ROOT/"security",ROOT/"state",ROOT/"incoming",
               *DESTINATIONS.values()]
    test="/usr/bin/python3"
    check=subprocess.run([test,"-I","-c",
        "import os,sys;sys.exit(1 if any(os.access(p,os.W_OK) for p in sys.argv[1:]) else 0)",
        *map(str,protected)],preexec_fn=demote,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if check.returncode:raise RuntimeError("operator can write root gateway; refusing privilege registration")

    sudoers=Path("/etc/sudoers").resolve(strict=True)
    original=sudoers.read_bytes();info=sudoers.stat()
    write(ROOT/"state/sudoers.original",original)
    # Append this exact command rule last so a later generic administrator
    # PASSWD rule cannot shadow it. The original complete policy is preserved.
    included=False
    rules=("\n# Smart Gatekeeper: fixed broker commands only\n"
           "Defaults!"+str(PROGRAM)+" !requiretty\n"+
           OWNER+" ALL=(root) NOPASSWD: "+
           ", ".join(str(PROGRAM)+" "+command for command in COMMANDS)+"\n").encode()
    target=Path("/etc/sudoers.d/smart_gatekeeper_broker_ops") if included else sudoers
    if included:
        if target.exists() or target.is_symlink():raise RuntimeError("sudo fragment already exists")
        write(target,rules,mode=0o440)
    else:write(target,original+rules,info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))
    home=Path(user.pw_dir).resolve()
    directory=home/".ssh";authorized=directory/"authorized_keys"
    previous=None;auth_info=None;added=False
    try:
        # DSM may omit visudo. Its actual policy parser + no-TTY owner lookup
        # validate the complete policy; a failure restores the original bytes.
        run(["/usr/bin/sudo","-n","-l","-U",OWNER])
        result=run(["/usr/bin/sudo","-n",str(PROGRAM),"status"],
                   preexec_fn=demote,start_new_session=True)
        json.loads(result.stdout)
        if directory.is_symlink():raise RuntimeError("SSH directory must not be a symlink")
        if not directory.exists():
            directory.mkdir(mode=0o700);os.chown(str(directory),user.pw_uid,user.pw_gid)
        if authorized.is_symlink():raise RuntimeError("authorized_keys must not be a symlink")
        previous=authorized.read_bytes() if authorized.exists() else b""
        if authorized.exists():auth_info=authorized.stat()
        write(ROOT/"state/authorized_keys.original",previous)
        restricted=('restrict,from="100.64.0.0/10",command="'+str(ROOT/"bin/ssh_dispatch.sh")+'" '+key+"\n").encode()
        if key.split()[1].encode() in previous:raise RuntimeError("dedicated key already present")
        write(authorized,previous+(b"\n" if previous and not previous.endswith(b"\n") else b"")+restricted,
              user.pw_uid,user.pw_gid,0o600)
        added=True
        receipt={"schema_version":1,"installed":True,"owner":OWNER,"commands":list(COMMANDS),
                 "general_shell":False,"docker_group_added":False,
                 "existing_deploy_key_preserved":True,"tailnet_only":True,
                 "source_hashes":{name:manifest[name] for name in DESTINATIONS}}
        output=Path("/var/run/sgk-broker-audit/broker-ops-setup.json")
        write(output,json.dumps(receipt,sort_keys=True).encode(),user.pw_uid,user.pw_gid)
        write(ROOT/"state/setup.json",json.dumps(receipt,sort_keys=True).encode())
        print(json.dumps({"broker_ops_access_installed":True,"general_shell":False,
                          "fixed_commands":len(COMMANDS),"existing_deploy_key_preserved":True}))
    except Exception:
        if added:
            write(authorized,previous,user.pw_uid,user.pw_gid,
                  stat.S_IMODE(auth_info.st_mode) if auth_info else 0o600)
        if included:target.unlink()
        else:write(sudoers,original,info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))
        raise


if __name__=="__main__":
    try:
        import sys
        if len(sys.argv)!=2:raise ValueError("exact staged package directory required")
        install(Path(sys.argv[1]))
    except Exception as error:
        print("setup_failed="+type(error).__name__+": "+str(error))
        raise SystemExit(1)
