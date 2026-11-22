import pathlib,sys,os,json,subprocess,hashlib,platform,winreg
HERE=pathlib.Path(__file__).resolve().parent
def main():
 tc,records,out=map(lambda x:pathlib.Path(x).resolve(),sys.argv[1:4]);out.mkdir(parents=True,exist_ok=False)
 source=records/'runs/44639720515/build/instrumented-src';dest=out/'src'
 subprocess.run([sys.executable,str(HERE/'prepare.py'),str(source),str(dest)],check=True)
 flags=['-include','string','-std=c++11','-O3'];units=['Main.cpp','StageC.cpp','solutions/HalfIntBranching.cpp','lib/Graph.cpp','lib/Translator.cpp','lib/CubicSolver.cpp','lib/HalfIntRelax.cpp']
 command=[str(tc/'g++.exe'),*flags,*[str(dest/u) for u in units],'-o',str(out/'StageD.exe')]
 p=subprocess.run(command,capture_output=True,env=dict(os.environ,PATH=str(tc)+os.pathsep+os.environ['PATH']))
 (out/'build.stdout.txt').write_bytes(p.stdout);(out/'build.stderr.txt').write_bytes(p.stderr);assert p.returncode==0,p.stderr.decode(errors='replace')
 sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
 with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as k:cpu=winreg.QueryValueEx(k,'ProcessorNameString')[0].strip()
 record=dict(experiment_commit=os.environ.get('GITHUB_SHA','local'),stage_c_experiment_commit='3244862ea2905ce24c811b962084c2b8a13310bd',records_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=records,text=True).strip(),upstream_commit='c0290698f6dfcc48b19b55e1aa915d8ecf61b0a4',command=command,flags=flags,compiler=subprocess.check_output([str(tc/'g++.exe'),'--version'],text=True),executable_sha256=sha(out/'StageD.exe'),source_hashes={p.relative_to(dest).as_posix():sha(p) for p in dest.rglob('*') if p.is_file()},os=platform.platform(),cpu=cpu,image=os.getenv('ImageOS','local')+' '+os.getenv('ImageVersion','unknown'),toolchain_sha256='54c2bb9962e8a30c8270e34c5efc3d5fee579f53087fa7d435b95fbba2af7b2b')
 (out/'build.json').write_text(json.dumps(record,indent=2))
if __name__=='__main__':main()
