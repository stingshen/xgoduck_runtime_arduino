// Host simulation of the actual bus parser: no hardware or motor commands.
#include <cassert>
#include <deque>
#include <vector>
#include <cstdint>
static uint32_t clockUs=100;
uint32_t micros(){return clockUs;}
#define K_FOREVER 0
#define K_USEC(x) (x)
struct k_mutex {};
void k_mutex_lock(k_mutex*,int){}
void k_mutex_unlock(k_mutex*){}
void k_sleep(uint32_t us){clockUs+=us;}
void k_msleep(uint32_t ms){clockUs+=1000*ms;}
struct SerialMock {
  std::vector<uint8_t> tx;
  std::deque<uint8_t> rx;
  std::vector<uint8_t> nextReply;
  void write(const uint8_t* p,size_t n){tx.assign(p,p+n);}
  void flush(){for(auto b:nextReply)rx.push_back(b);nextReply.clear();}
  bool available(){return !rx.empty();}
  uint8_t read(){auto b=rx.front();rx.pop_front();return b;}
} Serial1;
#include "../sketch/scs_bus.h"
#include "../sketch/protocol.h"
k_mutex motorsMu;
Motor motors[NUM_MOTORS];
std::vector<uint8_t> reply(uint8_t id,std::vector<uint8_t> data,uint8_t error=0){
  std::vector<uint8_t> p={255,255,id,uint8_t(data.size()+2),error};
  p.insert(p.end(),data.begin(),data.end());
  uint8_t sum=0;for(size_t i=2;i<p.size();++i)sum+=p[i];p.push_back(uint8_t(~sum));return p;
}
int main(){
  static_assert(sizeof(ServoPacket)==12);
  static_assert(sizeof(ServoReplyPacket)==14);
  for(int i=0;i<NUM_MOTORS;++i){motors[i].id=MOTOR_IDS[i];motors[i].sign=1;}
  readAllState();assert(Serial1.tx[5]==0x38 && Serial1.tx[6]==6);
  uint8_t value=0;
  Serial1.nextReply=reply(32,{74});
  assert(scsReadByte(32,0x3e,value,1000) && value==74);
  const std::vector<uint8_t> expected={255,255,32,4,2,62,1,154};
  assert(Serial1.tx==expected);
  assert(servoRxMask==0);
  auto bad=reply(32,{74});bad.back()^=1;
  for(auto p:{reply(31,{88}),reply(32,{74},1),reply(32,{74,75}),bad,std::vector<uint8_t>{}}){
    Serial1.nextReply=p;uint32_t start=micros();value=99;
    assert(!scsReadByte(32,0x3e,value,1000));
    assert(value==99 && micros()-start==1000);
  }
  // Unsolicited / late replies cannot write into the previous caller's output.
  for(auto b:reply(32,{80}))Serial1.rx.push_back(b);
  parseServoRx();assert(value==99);
  for(uint8_t id : {0,10,31,253}) {
    Serial1.nextReply=reply(id,{83});
    assert(scsReadByte(id,0x3e,value,1000) && value==83 && Serial1.tx[2]==id);
  }
  Serial1.nextReply=reply(31,{42});
  assert(scsReadByte(31,0x10,value,1000) && value==42 && Serial1.tx[5]==0x10);
  servoPdMask=0; // A two-byte reply above follows the original boot-gain parser.
  uint8_t kp=0,kd=0;Serial1.nextReply=reply(32,{5,10});
  assert(readServoGains(32,kp,kd) && kp==5 && kd==10 && servoPdMask==0);
  // The first valid response wins if duplicate replies are queued.
  Serial1.nextReply=reply(32,{74});auto duplicate=reply(32,{90});
  Serial1.nextReply.insert(Serial1.nextReply.end(),duplicate.begin(),duplicate.end());
  assert(scsReadByte(32,0x3e,value,1000) && value==74);
  auto before=Serial1.tx;
  assert(!scsReadByte(254,0x3e,value,1000));
  assert(!scsReadByte(32,0x3e,value,0));
  assert(Serial1.tx==before);
  // Normal six-byte joint feedback and broadcast boot gains still parse.
  for(auto b:reply(32,{0,8,0,0,0,0}))Serial1.rx.push_back(b);
  parseServoRx();assert(servoRxMask==(1<<12) && motors[12].fbPos==2048);
  for(auto b:reply(31,{7,12}))Serial1.rx.push_back(b);
  parseServoRx();assert(servoPdMask==(1<<11) && servoBootP[11]==7 && servoBootD[11]==12);
}
