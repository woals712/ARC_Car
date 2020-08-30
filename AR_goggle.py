# day4
# PIL, oled display  모듈 임포트
from PIL import Image, ImageDraw, ImageFont
import Adafruit_GPIO.SPI as SPI
import Adafruit_SSD1306
from datetime import datetime, timedelta, timezone
# button관련
import RPi.GPIO as GPIO
# google cloud speech 관련
from google.cloud import speech
from google.cloud.speech import enums
from google.cloud.speech import types 
import pyaudio
import queue
import threading    # 마이크 스트림 입력을 위한 스레드 
# websockets 관련
import asyncio
import websockets

# 환경설정
disp_width, disp_height = 64, 128 # oled portrait layout
RST, DC, SPI_PORT, SPI_DEVICE = 24, 25, 0, 0 # OLED pin 설정
TimeZone = timezone(timedelta(hours=+9)) # 서울표준시 사용

font_small = ImageFont.truetype("malgun.ttf",15)    # 폰트 준비
font_big = ImageFont.truetype("malgun.ttf", 25)

MODE_BUTTON, ACT_BUTTON = 5, 6 # 버튼 GPIO 핀할당

serverURI = "ws://192.168.0.103:5678" #websocket server

# mode 초기화
components=[]  
mode_index = 0
mode = None

# 콤포넌트 (모드) 추상 클래스
class Component():
    def __init__(self):
        self.screenImage = Image.new('1', (disp_width, disp_height))  # mode='1' 단색 비트맵이미지
        self.draw = ImageDraw.Draw(self.screenImage)    # PIL draw 핸들

    # 모드버튼 눌려 모드 진입할 때 실행
    def whenActivated(self):
        pass

    # 표시할 이미지 업데이트
    def update(self):
        self.draw.rectangle((0,0,disp_width,disp_height), fill=0)    # 화면 지움

    #현재 시간 확인
    def getCurrentTime(self):
        return datetime.now(TimeZone)
    
    # 가운데 정렬- 텍스트를 화면중앙에 정렬하고자 할 때 시작점 xy 리턴
    def getTextCenterAlignXY(self, text, font):
        centerX = (disp_width -  self.draw.textsize(text,font=font)[0]) // 2
        centerY = (disp_height - self.draw.textsize(text, font=font)[1]) // 2
        return (centerX, centerY)

    # 텍스트를 입력받으면 화면 가로 폭에 맞추어 줄 바꾸어 리턴
    def textMultiliner(self, text, font):
        
        text_multiline=''   # 최종적으로 보여질 화면에 맞추어 줄바꿈 한 글줄
        if text is not '':
            # 내용이 디스플레이 폭에 맞추어 줄바꿈 되도록, text의 내용을 한자씩 새로운 문자열에 추가하면서 가로폭을 재보고, disp_width  보다 커지면 '\n'넣어줌.
            for character in text:
                text_multiline += character
                if self.draw.textsize(text_multiline, font=font)[0] >= disp_width:
                    text_multiline = text_multiline[:-1]+'\n' + text_multiline[-1]  # 마지막 글자 바로앞에서 줄바꿈           
            
        return text_multiline

    # MODE_BUTTON 이 눌렸을 때
    def modeButtonPressed(self):
        print(f"MODE button pressed.")
        pass

    # ACT_BUTTON 이 눌렸을 때
    def actButtonPressed(self):
        print(f"ACT button pressed.")
        pass

# 시계 콤포넌트
class ClockComponent(Component):
    
    # 현재시간을 확인해 표시할 이미지 만듬.
    def update(self):
        super().update()

        # 현재시간 확인
        now = self.getCurrentTime()

        # 시계화면 구성     
        self.draw.text((2,30), now.strftime('%p'), font = font_small, fill=1 ) #am/pm
        self.draw.text((0,50), now.strftime('%I:%M'), font = font_big, fill=1 ) # 시:분
        self.draw.text((40,80), now.strftime('%S'), font = font_small, fill=1 ) # :초

# 달력 콤포넌트
class CalendarComponent(Component):
    
    # 현재시간을 확인해 표시할 이미지 만듬.
    def update(self):
        super().update()

        # 현재시간 확인
        now = self.getCurrentTime()

        # 달력화면 구성
        year = str(now.year)    # 년도
        self.draw.text(( self.getTextCenterAlignXY(year, font_small)[0],20), year, font = font_small, fill=1 ) 

        month = str(now.month)  # 월
        self.draw.text((20,40), month, font = font_big, fill=1 ) 
        self.draw.text((20+len(month)*13,50), '월', font = font_small, fill=1 ) # 글자수에 따라 간격 조정

        day = str(now.day)  # 일
        self.draw.text((20,65), day, font = font_big, fill=1 ) 
        self.draw.text((20+len(day)*13,75), '일', font = font_small, fill=1 ) 

        yoil = '월화수목금토일'[now.weekday()] # weekday(): 요일을 0~6으로 리턴
        self.draw.text(( self.getTextCenterAlignXY(yoil+'요일', font_small)[0],95), yoil+'요일', font = font_small, fill=1 ) # 요일

# 음성인식 콤포넌트
class VoiceComponent(Component):
    
    def __init__(self):
        super().__init__()

        # 마이크 활성화 여부 (버튼 눌러 토글 시킴)
        self.is_mic_active = False

        # 이전에 해석된 내용이 담길 곳
        self.lasttime_you_said = [] 
        # 화면에 표시될 단어가 담길 곳
        self.words_to_show=[]
        # 웹소켓 서버로 전달할 명령어 - words_to_show는 화면에서 사라지면 안되지만 command_list는 사용하면 소모됨
        self.command_list=[]

        # 레코딩 특성
        self.rate = 16000   # Hz
        self.chunk = int(self.rate/10)   
        self.encoding = 'LINEAR16'   # enums.RecognitionConfig.AudioEncoding.LINEAR16
        self.max_alternatives = 1
        self.language_code = 'ko-KR'

        # google-cloud-speech request config 설정
        self.client = speech.SpeechClient()
        self.client_config = types.RecognitionConfig(
            encoding= self.encoding,
            sample_rate_hertz=self.rate,
            max_alternatives=self.max_alternatives,     # 가장 가능성 높은 1개 alternative만 받음.
            language_code = self.language_code
            )
        self.streaming_config = types.StreamingRecognitionConfig(
            config=self.client_config,
            interim_results = True  #  과정을 보여줌.
            ) 
        
    def whenActivated(self):
        super().update()
        
    def update(self):
        super().update()
        
        # 보이스 입력 작동중일땐 입력받은 내용 디스플레이
        if self.is_mic_active is True:   
            text = ' '.join(self.words_to_show) + '\n...' # 마이크 작동중 표시 추가   
        # 마이크 버튼 눌리지 않았다면
        else:
            text = 'press\nACTION\nfor\nvoice\ninput'

        # 화면 폭에 맞추어 줄바꿈
        text = self.textMultiliner(text, font_small)    
        # 화면 중앙에 정렬해 표시
        self.draw.text( self.getTextCenterAlignXY(text, font_small), text, font = font_small, fill=1 )

    # ACT_BUTTON 한번 누르면 active, 다시 한 번 누르면 idle
    def actButtonPressed(self):
        super().actButtonPressed()

        # 플래그 토글
        self.is_mic_active = not self.is_mic_active  

        # 버튼 눌리면 마이크 스트림 스레드 & websocket connection 생성 
        if self.is_mic_active == True:
            #버튼이 눌릴 때마다 새로운 오브젝트 생성.
            mic_stream_thread = threading.Thread(target = self.doVoiceRecognition)
            mic_stream_thread.start()
            websocket_thread = threading.Thread(target = self.doWebsocketClient)
            websocket_thread.start()
        else:
            pass

    def doWebsocketClient(self):
        try:
            asyncio.run(self.websocket_client())
        except websockets.WebSocketException:
            print('네트워크 확인')

    async def websocket_client(self):
        async with websockets.connect(serverURI) as websocket:
            while True:   
                if self.command_list is not []:
                    for command in self.command_list:
                        await websocket.send(command)
                        print(f"{command} sent")
                        
                        resp = await websocket.recv()
                        print(f"{resp} received.")

                    self.command_list = [] # 사용한 후엔 소모됨
                else:
                    pass  

                # ACTION 버튼 눌리면 루프 중지
                if self.is_mic_active == False:
                    break

    def doVoiceRecognition(self):        
        # mic로부터 오디오스트림 생성      
        MicStream = MicrophoneStream(self.rate, self.chunk)
        
        # 버튼이 다시 눌렸는지 감지(is_mic_active)해 입력 마치는 것으로...
        try:
            with MicStream as stream:   
                audio_generator = stream.generator()
                requests = (types.StreamingRecognizeRequest(audio_content=content) for content in audio_generator)  # 요청 생성

                responses = self.client.streaming_recognize(self.streaming_config, requests)
                self.listen_print_loop(responses)   # 결과 출력. requests, responses 모두 iterable object

        except InputEnded:
                print(f"input ended")

    def listen_print_loop(self,responses):
        # response 처리
        for response in responses:

            # act_button 눌리는지 감지해 루프 중지-InputEnded 예외발생       
            if self.is_mic_active is False:
                raise InputEnded()

            # results를 포함하지 않는다면
            if not response.results:
                continue    
            # 만약 response가 둘 이상의 result를 포함하고 있더라도 result[0] 이 확정(is_final=True) 되면 이전의 result[1]이 다음번에 result[0]이 되어 응답으로 오게되므로 우리는 results[0]만 고려한다. 
            result = response.results[0]
            if not result.alternatives:
                continue

            # 확실성 가장 높은 alternative의 해석
            transcript = result.alternatives[0].transcript
            
            # transcript 중 예전에 사용자에게 보여주었던 앞부분은 제외하고 변경이 있는부분, 추가된 부분만 보여주자.
            tr = transcript.split() # transcript list화.
            tr_words_count = len(tr) 
            lasttime_words_count = len(self.lasttime_you_said)

            # 만약 이전에 보여준게 없다면, 처음이라면
            if self.lasttime_you_said == []:            
                self.words_to_show = tr
                self.lasttime_you_said = tr

            # 변경된 내용이 없다면
            elif tr == self.lasttime_you_said:
                #self.words_to_show = self.words_to_show
                #self.lasttime_you_said = self.lasttime_you_said

            # 항목의 수가 줄어들었다면
            elif tr_words_count < lasttime_words_count:
                # 내용도 바뀌었다면
                if tr != self.lasttime_you_said[:tr_words_count]:
                    self.words_to_show=[] 
                    for i in range(tr_words_count):    
                        if tr[i] != self.lasttime_you_said[i]:  # 이전과 다른 항목이 있다면 self.workds_to_show에 추가한다.  
                            self.words_to_show.append(tr[i]) 
                # 항목이 줄어들었으나 내용이 같다면
                else:
                    pass       

                self.lasttime_you_said = tr 

            # 일반적인 경우 
            else:    
                # 동일한 부분은 무시하고 변경있는 부분만 복사             

                self.words_to_show=[] 
                for i in range(lasttime_words_count):    
                    if tr[i] != self.lasttime_you_said[i]:  # 이전과 다른 항목이 있다면 그곳부터
                        break
                    i += 1            # 다른 곳은 없지만 갯수가 늘었다면 늘어난 아이템부터
                # self.words_to_show에 추가한다.
                for j in range(i,tr_words_count):   
                    self.words_to_show.append(tr[j])

                self.lasttime_you_said = tr 

            # command_list와 words_to_show는 동일한 내용이지만 command_list는 사용 후 소모됨.
            self.command_list = self.words_to_show
            
            
            
# 음성인식 모드에서 ACT_Button 눌리면 발생하는 예외
class InputEnded(Exception):
    pass

# 음성데이터 스트림
class MicrophoneStream:
    def __init__(self,rate,chunk):
        self._rate=rate
        self._chunk=chunk
        self._buff=queue.Queue()    # pyaudio가 전달해주는 데이터를 담을 큐
        self.closed=True    # audio interface가 연결되었는지

    # 파이썬 context manager  사용.
    def __enter__(self):
        print("mic start")
        self._audio_interface = pyaudio.PyAudio()   # pyaudio 참고문서: https://people.csail.mit.edu/hubert/pyaudio/docs/
        self._audio_stream = self._audio_interface.open(   # pyaudio.open()은 pyaudio.Stream object를 리턴.
            format = pyaudio.paInt16, #16bit 다이나믹 레인지
            channels = 1,
            rate = self._rate,
            input = True,   # 마이크로부터 입력되는 스트림임 명시
            frames_per_buffer=self._chunk,
            stream_callback=self._fill_buffer,  # pyaudio에서 한 블록의 데이터가 들어올 때 호출되는 콜백
        )
        self.closed = False
        return self

    def __exit__(self, type, value, traceback):
        print("mic ends")
        self._audio_stream.stop_stream()
        self._audio_stream.close()
        self.closed = True
        self._buff.put(None)
        self._audio_interface.terminate()   # 끝날 때 반드시 pyaudio 스트림 닫도록 한다.

    # pyaudio.Stream에서 호출되는 콜백은 4개 매개변수 갖고, 2개값 리턴한다. pyaudio문서 참고.
    def _fill_buffer(self, in_data, frame_count, time_info, status_flags):
        self._buff.put(in_data) # 큐에 데이터 추가
        return None, pyaudio.paContinue
    
    # 한 라운드의 루프마다 현재 버퍼의 내용을 모아서 byte-stream을 생산함.
    def generator(self):
        while not self.closed:
            # Use a blocking get() to ensure there's at least one chunk of
            # data, and stop iteration if the chunk is None, indicating the
            # end of the audio stream.
            chunk = self._buff.get()
            if chunk is None:
                return
            data = [chunk]

            # Now consume whatever other data's still buffered.
            while True:
                try:
                    chunk = self._buff.get(block=False) # 가장 오래된 데이터부터 순차적으로 data[]에 추가함.
                    if chunk is None:
                        return
                    data.append(chunk)
                except queue.Empty: # 큐에 더이상 데이터가 없을 때까지
                    break

            yield b''.join(data)    # byte-stream

# 버튼 초기화
def initButton():
    GPIO.setmode(GPIO.BCM)
    buttons = [MODE_BUTTON, ACT_BUTTON]
    GPIO.setup(buttons, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # button을 input으로, 내장 풀업 활성화

    # 인터럽트 스레드 시작. debounce 적용.
    for btn in buttons:
        GPIO.add_event_detect(btn, GPIO.FALLING, callback=buttonPressed, bouncetime=200)

# 버튼 인터럽트 콜백함수
def buttonPressed(channel):
    global mode_index
    global mode
    global components

    print(f"button @{channel} pressed!")

    # 모드버튼 눌리면 모드 전환
    if channel == MODE_BUTTON:  
        
        mode_index += 1     # 0이었으면 1, 1이었으면 2, 2였으면 0
        if mode_index == 3:
            mode_index = 0
        mode = components[mode_index]
        mode.whenActivated()    # 모드 진입할 때 실행되어야 하는 코드

    # mic버튼 눌리면 현재의 mode.actButtonPressed() 실행
    if channel == ACT_BUTTON:
        mode.actButtonPressed()

# 메인 
def main():
    # oled 디스플레이 초기화
    oled = Adafruit_SSD1306.SSD1306_128_64(rst=RST, dc=DC, spi=SPI.SpiDev(SPI_PORT, SPI_DEVICE, max_speed_hz=8000000))
    oled.begin()
    oled.clear()
    oled.display()

    # mode 초기화
    global components
    components=[ClockComponent(), CalendarComponent(), VoiceComponent()]  # 시계모드 & 달력모드
    global mode_index
    global mode
    mode = components[mode_index]

    # 버튼 초기화
    initButton()

    # 무한반복
    # 키보드 인터럽트(Ctrl-C)가 있으면 종료
    try:
        while True:
            # 현재 모드에 따라 업데이트 실행
            mode.update()

            # oled 디스플레이 업데이트
            flippedImage = mode.screenImage.transpose(Image.FLIP_LEFT_RIGHT) # 화면을 기기에 맞추어 세로로 회전, 거울상만들기.
            rotatedImage = flippedImage.transpose(Image.ROTATE_90)  # 화면을 가로로 돌림

            oled.image(rotatedImage)
            oled.display()

    except KeyboardInterrupt:
        print("사용자에 의해 실행을 중단합니다...")
        oled.clear()
        oled.display()
    except :
        print("알 수 없는 오류로 종료합니다...")
    finally : 
        GPIO.cleanup()

if __name__ == '__main__':
    main()
