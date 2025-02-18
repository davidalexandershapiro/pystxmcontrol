//VARIABLES
char data;
int softGATE=0;
int dwell1 = 100;
int dwell2 = 0;
String readStr;
int shutterMASK=1;

//PIN assignments
int gateCOMMAND=13;
//int triggerIN=12;
int shutterOUT=11;
int ccdOUT=10;
int testPIN = 9;
int pixelPIN = 8;

void setup() { 
  Serial.begin(115200);
  pinMode(testPIN, OUTPUT);
  pinMode(gateCOMMAND, OUTPUT);
  //pinMode(triggerIN, INPUT);
  pinMode(shutterOUT,OUTPUT);
  pinMode(ccdOUT,OUTPUT);
  digitalWrite(shutterOUT, LOW);
  digitalWrite(gateCOMMAND, LOW);
  digitalWrite(ccdOUT, LOW);
  digitalWrite(testPIN,LOW);
  //attachInterrupt(digitalPinToInterrupt(triggerIN),pixelPulse,RISING);
  Serial.println("<Arduino ready>");
}

//void pixelPulse(){
//   digitalWrite(ccdOUT, HIGH);
//   digitalWrite(shutterOUT, HIGH);
//   //delay(5);
//   digitalWrite(shutterOUT, LOW);
//   digitalWrite(ccdOUT, LOW);
//}

void loop() {
  while (Serial.available()){
    data = Serial.read();
    readStr += data;
  }
  if (readStr.length() == 11) {
    dwell1 = readStr.substring(0,3).toInt();
    dwell2 = readStr.substring(4,7).toInt();
    shutterMASK = readStr.substring(8).toInt();
    softGATE = readStr.substring(10).toInt();
    //Serial.println(dwell1);
    readStr = "";
  }
  if (dwell1 == 0){
    if (softGATE == 1){
      digitalWrite (gateCOMMAND, HIGH);
      digitalWrite(ccdOUT,HIGH);
      if (shutterMASK == 1){
        digitalWrite(shutterOUT, HIGH);  
      }
    }             
    else if (softGATE == 0){
      digitalWrite (gateCOMMAND, LOW);
      digitalWrite(ccdOUT,LOW);
      digitalWrite(shutterOUT, LOW);
    }
  }
  else {
    if (softGATE == 1){
      if (shutterMASK == 1){
        digitalWrite(shutterOUT, HIGH);
      }
      digitalWrite(ccdOUT, HIGH);
      delay(dwell1);
      digitalWrite(shutterOUT, LOW);
      digitalWrite(ccdOUT, LOW);
      //if (dwell2 > 0){
      //  if (shutterMASK == 1){
      //    digitalWrite(shutterOUT, HIGH);
      //  }
      //  digitalWrite(ccdOUT, HIGH);
      //  delay(dwell2);
      //  digitalWrite(shutterOUT, LOW);
      //  digitalWrite(ccdOUT, LOW);        
      //}
      softGATE = 0;
    }
    else{
      digitalWrite(shutterOUT, LOW);
      digitalWrite(ccdOUT, LOW);
    }
  }
}
