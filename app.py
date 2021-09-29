from flask import Flask, json, request, jsonify, abort
import time
import requests
import asyncio
import asgiref


from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql.sqltypes import ARRAY
from dotenv import load_dotenv
import time
import os

app = Flask(__name__)

load_dotenv() #api 접속을 위한 private key값을 .env 파일에 넣어 보안을 유지할 수 있으며 직접 입력하지 않아 편함

POSTGRES_ID=os.getenv("POSTGRES_ID")
POSTGRES_PW=os.getenv("POSTGRES_PW")
DATABASE_URL=os.getenv("DATABASE_URL")
# PostgreSQL : 오픈 소스 객체-관계형 데이터베이스 시스템(ORDBMS)를 사용
# app.config['SQLALCHEMY_DATABASE_URI'] = f"postgresql://{POSTGRES_ID}:{POSTGRES_PW}@localhost/kakao-flask"


app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL #SQLAlchemy에서 사용할 데이터베이스의 위치를 설정
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False #True 사용시 추가적인 메모리가 필요하므로 False 설정(이벤트 처리 옵션)


app.debug = True

db = SQLAlchemy(app) # SQLAlchemy 객체 생성


class Customer(db.Model): # db.Model을 통해 SQLAlchemy의 기능 사용을 위한 상속 실행
    __tablename__="Customer" # 데이터 베이스 이름 설정

    id = db.Column(db.Integer, primary_key=True) # 사용자 id
    kakao_id = db.Column(db.Integer) # 카카오 id
    datas = db.relationship('ChatList', backref='customer') #ChatList에서 Customer.id와 같이 사용자의 id에 접근할 수 있음

class ChatList(db.Model):
    __tablename__="ChatList"# 데이터 베이스 이름 설정

    id = db.Column(db.Integer, primary_key=True) # ChatList id
    chat_open_date = db.Column(db.String())
    customer_id = db.Column(db.Integer, db.ForeignKey('Customer.id'), nullable=False) # 외래키 설정
    messages = db.relationship('Chat', backref='chatlist')

class Chat(db.Model):
    __tablename__='Chat'# 데이터 베이스 이름 설정

    id = db.Column(db.Integer, autoincrement=True, primary_key=True)
    timestamp = db.Column(db.DateTime)
    imotion = db.Column(db.String())
    words = db.Column(ARRAY(db.String))
    user_message = db.Column(db.String())  # 사용자의 메시지 저장
    reply = db.Column(db.String())  # 인공지능 모델의 답변 저장
    chatlist_id = db.Column(db.Integer, db.ForeignKey('ChatList.id'), nullable=False)


db.create_all() # 데이터 베이스 초기화


wait_count = 0
message_list = []
count_start = False


def find_or_create_user(user_id):
    try:
        customer = db.session.query(Customer).filter(Customer.kakao_id==int(user_id)).one()
        return customer
    except:
        customer = Customer(kakao_id=int(user_id))
        db.session.add(customer)
        db.session.commit()
        return customer

def find_or_create_date(today, customer):
    try:
        chatlist = db.session.query(ChatList).with_parent(customer).filter(ChatList.chat_open_date == today).one()     
        return chatlist
    except:
        chatlist = ChatList(chat_open_date=today, customer=customer)
        db.session.add(chatlist)
        db.session.commit()
        return chatlist

# time_stamp:시간, imotion:숫자, words:단어 리스트, chatlist:귀속할 챗리스트
def create_chat(time_stamp, imotion, words, chatlist, message_to_model, reply): #사용자 대화, #ai 답변)
    chat = Chat(timestamp=time_stamp, imotion=imotion, words=words, chatlist=chatlist, user_message=message_to_model,
                reply=reply) #사용자 대화(user_message), #ai 답변(reply)
    db.session.add(chat)
    db.session.commit()
    return

def get_today():
    today = time.localtime(time.time())
    return f"{today.tm_year}-{today.tm_mon}-{today.tm_mday}"


def text_from_chat(request_data, imotion, words, message_to_model, reply):
    user_id = request_data['userRequest']['user']['id']
    time_stamp = time.ctime(time.time())
    today = get_today()

    customer = find_or_create_user(user_id)

    chatlist = find_or_create_date(today, customer)
    
    create_chat(time_stamp, imotion, words, chatlist, message_to_model, reply)


async def waiting(body):
    global wait_count
    global message_list

    # hello_code가 실행될때마다 wait_count 가 0으로 초기화
    # 새로운 대화가 넘어오지 않으면 1초마나 wait_count가 1씩 누적
    while wait_count < 6:
        wait_count = wait_count + 1
        time.sleep(1)
        # 아무동작 없이 5초가 흐르면 누적된 대화 리스트를 합쳐 모델API로 보냄
        if wait_count > 4:
            global count_start
            count_start = False
            message_to_model = jsonify("".join(message_list)) #사용자가 정해진 시간안에 입력한 모든 메시지
            # API로 리턴 받은 대답을 리턴해줌
            imotion, words, reply = await requests.post('/AI/sendMessage/', message_to_model) # 인공지능 모델로 전송하여 답변 요청
            # 대화 내용과 결과를 DB에 저장
            text_from_chat(body, imotion, words, message_to_model, reply)

            #내가 해야할일은 reply와 message_to_model의 데이터를 데이터베이스에 저장해야함

            # 대답후 사용자의 대화를 받기 위해 리스트 초기화
            message_list = [] # 사용자의 다음 메시지를 받기 위해 초기화
            return reply # 답변 return

# 카톡으로부터 요청
@app.route('/backend/sendMessage',methods=['POST'])
async def get_massages_from_chatbot():
    global count_start
    global wait_count
    # 입력이 들어올때마다 카운트 0으로
    wait_count = 0

    # 넘어온 JSON에서 메세지 받아 임시 리스트에 append
    body = request.get_json() # POST 방식으로 body에 데이터를 실어서 보내기
    message_to_model = body['userRequest']['utterance']
    message_list.append(message_to_model)

    # 처음 대화가 시작되는 순간에만 사용하기 위해 count_start 를 바꿔줌
    # 두번째 말풍선부턴 실행되지 않음
    if count_start == False:
        count_start = True
        # waiting() 으로 완성된 문구를 리턴받음
        result = await waiting(body)
        return result # 답변 return

    return "loading..."



# 프론트로부터 요청(대시보드에 전송될 데이터)
@app.route('/frontend/getUsers/')
def request_users_data():# 데이터 베이스에 저장된 유저 정보 모두 전송
    customers = db.session.query(Customer).all()
    data = []
    for i in customers:
        json = {"id": i.id, "kakao_id": i.kakao_id}
        data.append(json)
    return jsonify(data) # json 형태로 return

@app.route('/frontend/getUser/<int:id>/')
def request_user_data(id):# 카카오 id 그리고 카카오 id와 일치하는 채팅 채팅이 시작된 일자
    customer = db.session.query(Customer).filter(Customer.kakao_id == id).one()
    data = []
    for date in customer.datas:
        json = {"id": id, "kakao_id":customer.kakao_id,"date":date.chat_open_date}
        data.append(json)
    return jsonify(data) # json 형태로 return

@app.route('/frontend/getUser/<int:id>/getDate/<date>/')
def request_date_data(id, date): # id와 날짜를 받아옴
    imotions = {}
    words = {}
    conversation = [] # 사용자의 메시지와 인공지능이 답변한 메시지를 담을 list

    customer = db.session.query(Customer).filter(Customer.kakao_id == id).one() # .one -> 최초 1회만 수행하도록 만들어주는 메소드
    date = db.session.query(ChatList).with_parent(customer).filter(ChatList.chat_open_date == date).one() #Customer(데이블)에서 카카오 id로 검색된 데이터가 담긴 customer.date 값과 일치하는 ChatList 데이터 검색

    for message in date.messages:
        try:
            imotions[str(message.imotion)] += 1
        except:
            imotions[str(message.imotion)] = 1
        for word in message.words:
            try:
                words[word] +=1
            except:
                words[word] = 1
        conversation.append(message.user_message) #사용자의 답변을 먼저 추가
        conversation.append(message.reply)#이후 인공지능의 답변 추가, 인덱스를 통해 사용자와 인공지능의 답변을 추출 가능

    def f1(x):
        return x[0]

    sorted_imotions = sorted(imotions.items(), key=f1, reverse=True)
    sorted_words = sorted(words.items(), key=f1, reverse=True)

    return jsonify({"imotion_rank":sorted_imotions,"word_rank":sorted_words})


if __name__ == '__main__':
    app.run(debug=True)