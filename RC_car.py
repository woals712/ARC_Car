# day4_car.py

from Raspi_MotorHAT import Raspi_MotorHAT, Raspi_DCMotor
# websockets
import asyncio
import websockets

# 모터 설정
mh = Raspi_MotorHAT(addr=0x6f)
dcMotor = mh.getMotor(3)    # M3단자에 모터 연결
speed = 125 # 기본 속도 0~255
dcMotor.setSpeed(speed)
# 서보 설정
servo = mh._pwm
servo.setPWMFreq(60)
# 서버 ip address
ServerIP = "192.168.0.103"

# 앞으로
def go():
    dcMotor.run(Raspi_MotorHAT.FORWARD)

# 뒤로
def back():
    dcMotor.run(Raspi_MotorHAT.BACKWARD)

# 모터 작동 중지
def stop():
    dcMotor.run(Raspi_MotorHAT.RELEASE)

# 빠르게
def speedUp():
    global speed
    speed = 255 if speed >= 235 else speed+20 #최대255, 20단위로 증감
    dcMotor.setSpeed(speed)

# 느리게
def speedDown():
    global speed
    speed=0 if speed <= 20  else speed-20  # 최하 0
    dcMotor.setSpeed(speed)

# 각도만큼 핸들 틀기
def steer(angle=0): # 각도 -90˚~ +90˚
    #test
    print(f"steer {angle}˚")
    if angle <= -60: # 서보의 작동범위는 좌우 양 극단의 30˚까지는 가지 않는다.
        angle = -60 
    if angle >= 60:
        angle = 60 
    pulse_time = 200+(614-200)//180*(angle+90)  # 200:-90˚ ~ 614:+90˚ 비율에 따라 맵핑

    servo.setPWM(0,0,pulse_time)

# 우회전
def steer_right():
    steer(30)

# 좌회전
def steer_left():
    steer(-30)

# 핸들 중앙
def steer_center():
    steer(0)

# 클라이언트로부터 받을 수 있는 명령어와 대응하는 함수
command = ['앞으로', '뒤로', '정지', '빠르게', '느리게', '오른쪽', '왼쪽', '중앙']
func = [go, back, stop, speedUp, speedDown, steer_right, steer_left, steer_center]

async def voice_drive(websocket, path):
    try:
        loop = asyncio.get_running_loop()   # asyncio  이벤트 루프
        
        while True:
            # 클라이언트로부터 메시지 받음
            message = await websocket.recv()
            print(f"message: {message}")
            # 메시지에 해당하는 index의 func 실행
            if message in command:
                print("message matches!")
                await loop.run_in_executor(None, func[command.index(message)])  # run_in_executor() 사용해 별도 스레드에서 비동기적으로 함수 실행
            
                response = 'OK'
            else:
                print("no command...")
                response = 'not a command'
            # 응답 보냄
            await websocket.send(response)
    except websockets.WebSocketException:
        print("네트워크 확인")

async def main():
    try:
        # websocket 서버 작동
        server = await websockets.serve(voice_drive, host = ServerIP, port=5678)
        print("server ready!")
        await server.wait_closed()        
    except KeyboardInterrupt:
        print("\n사용자의 요청으로 종료합니다..")
    except:
        print("\n알 수 없는 오류입니다.")
    finally:    # 종료할 때는 모든 모터 멈추기
        mh.getMotor(1).run(Raspi_MotorHAT.RELEASE)
        mh.getMotor(2).run(Raspi_MotorHAT.RELEASE)
        mh.getMotor(3).run(Raspi_MotorHAT.RELEASE)
        mh.getMotor(4).run(Raspi_MotorHAT.RELEASE)

if __name__ == "__main__":
    asyncio.run(main())