#ifndef STAGE_C_H
#define STAGE_C_H
#include <string>
#include <cstdint>
#include <stdexcept>
class Graph;
class BranchingSolution;
struct StageStop { std::string reason; int code; };
class StageC {
public:
 static void init(int,char**);
 static void guard();
 static bool isReplay();
 static int replay();
 static void finish(const std::string&);
 static std::string state(BranchingSolution*,Graph&,int,int,int);
 static void restore(const std::string&,BranchingSolution*&,Graph&,int&,int&,int&);
 static std::string decision(BranchingSolution*,Graph&,int,int,int,bool&,bool&);
};
struct StageFrame { StageFrame(); ~StageFrame(); };
struct StageDecision {
 BranchingSolution* solver; Graph& graph; int phase,pivot,root;
 uint64_t id,startHash,startCount; bool ambiguous;
 StageDecision(BranchingSolution*,Graph&,int,int,int);
 ~StageDecision();
};
#endif
