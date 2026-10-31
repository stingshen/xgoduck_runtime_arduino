const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const nodes={};
for(const id of ['supply-voltage','supply-voltage-detail','read-voltage','voltage-servo-id'])
  nodes[id]={value:'32',textContent:'',disabled:false,addEventListener(event,handler){this.handler=handler;}};
let requests=0,complete;
const context=vm.createContext({document:{getElementById:id=>nodes[id]},AbortSignal,
  fetch:async(url,options)=>{requests++;assert.equal(url,'/api/voltage/read');assert.equal(options.method,'POST');assert.equal(JSON.parse(options.body).servo_id,31);
    return new Promise(resolve=>{complete=()=>resolve({ok:true,json:async()=>({accepted:true,pending:true})});});}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../assets/voltage.js'),'utf8'),context);
(async()=>{
  assert.equal(requests,0); // Opening the page never reads the servo.
  context.showSupplyVoltage({connected:true,pending:false,available:false,retry_after_ms:0});
  assert.equal(nodes['read-voltage'].disabled,false);
  nodes['voltage-servo-id'].value='254';await nodes['read-voltage'].handler();assert.equal(requests,0);
  nodes['voltage-servo-id'].value='31';
  const first=nodes['read-voltage'].handler();
  await nodes['read-voltage'].handler();assert.equal(requests,1);
  context.showSupplyVoltage({connected:true,pending:true});assert.equal(nodes['read-voltage'].disabled,true);
  complete();await first;
  context.showSupplyVoltage({connected:true,pending:false,available:true,servo_id:31,volts:7.4,age_ms:32000,retry_after_ms:0});
  assert.equal(nodes['supply-voltage'].textContent,'7.4 V');
  assert.match(nodes['supply-voltage-detail'].textContent,/ID 31.*32 秒前/);
  assert.equal(nodes['read-voltage'].disabled,false);
  context.showSupplyVoltage({connected:true,pending:false,error:'读取超时，请重试',available:false,retry_after_ms:0});
  assert.match(nodes['supply-voltage-detail'].textContent,/超时/);
  context.showSupplyVoltage(null);assert.equal(nodes['read-voltage'].disabled,true);
  assert.equal(requests,1);console.log('Voltage button tests passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
