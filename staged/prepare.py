"""Derive Stage D exclusively from the archived Stage C build's source; do not edit Stage C."""
import pathlib,sys,shutil,json,hashlib
source,dest=map(pathlib.Path,sys.argv[1:3]);record=json.loads((source.parent/'build_record.json').read_text())
assert not dest.exists();dest.mkdir(parents=True)
for name,digest in record['instrumented_source_hashes'].items():
 p=source/name;assert hashlib.sha256(p.read_bytes()).hexdigest()==digest
 q=dest/name;q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q)
p=dest/'StageC.cpp';s=p.read_text()
s=s.replace('uint64_t replayOffset=0,replayLength=0;','uint64_t replayOffset=0,replayLength=0;\nint forcedPivot=-1;')
s=s.replace('#include <algorithm>', '#include <algorithm>\n#include <functional>')
s=s.replace('int forcedPivot=-1;', 'int forcedPivot=-1;\nstd::function<void()> armCheckpoint;\nauto lastArmCheckpoint=chrono::steady_clock::now();')
s=s.replace(' if(cpu()>=cpuLimit)', ' if(armCheckpoint&&now-lastArmCheckpoint>=chrono::milliseconds(100)){lastArmCheckpoint=now;armCheckpoint();}\n if(cpu()>=cpuLimit)')
s=s.replace(' if(argc==6 && string(argv[2])=="--replay")', ' if((argc==6 && string(argv[2])=="--replay") || (argc==7 && string(argv[2])=="--pivot"))')
s=s.replace(' if(eventLog){events.open', ' if(argc==7)forcedPivot=atoi(argv[6]);\n if(eventLog){events.open')
s=s.replace('chrono::milliseconds(100)','chrono::milliseconds(1)')
s=s.replace('throw StageStop{"external_stop",75};','{ifstream stop(directory+"/STOP");string reason;getline(stop,reason);throw StageStop{reason.empty()?"external_stop":reason,75};}')
old='StageFrame::StageFrame(int proc,BranchingSolution*s){++level;frames.push_back(FrameRec{proc,false,leafStamp,s});nodesEntered[proc][s->isSub?1:0]++;StageC::guard();}'
new='StageFrame::StageFrame(int proc,BranchingSolution*s){StageC::guard();++level;frames.push_back(FrameRec{proc,false,leafStamp,s});nodesEntered[proc][s->isSub?1:0]++;}'
assert old in s;s=s.replace(old,new)
a=s.index('int StageC::replay(){')
s=s[:a]+(pathlib.Path(__file__).parent/'continuation.cpp.inc').read_text()
p.write_text(s)
