import cv2
import os
import numpy as np
from sklearn.neighbors import KNeighborsClassifier
from joblib import dump, load
from datetime import datetime
import cloudinary
import cloudinary.uploader
from pymongo import MongoClient
from io import BytesIO
from shared_state import last_detected_user
from dotenv import load_dotenv

MODEL_PATH = 'facenet_model.pkl'
CASCADE_PATH = 'haarcascade_frontalface_default.xml'

# Load environment variables
load_dotenv()

# Configure Cloudinary
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

# MongoDB connection
mongo_uri = os.getenv("MONGO_URI")
client = MongoClient(mongo_uri)  # ✅ correct usage
db = client["face_db"]
faces_collection = db["faces"]

# Train model using in-memory collected face images
def train_model_memory(data):
    X, y = [], []
    for item in data:
        X.append(item['img'].flatten())
        y.append(item['name'])
    if X:
        clf = KNeighborsClassifier(n_neighbors=3)
        clf.fit(X, y)
        dump(clf, MODEL_PATH)

class VideoCamera:
    def __init__(self, mode='detect', name=None, cid=None, dob=None, phone=None, password=None):
        self.video = cv2.VideoCapture(0)
        self.face_cascade = cv2.CascadeClassifier(CASCADE_PATH)
        self.mode = mode
        self.name = name
        self.cid = cid
        self.dob = dob
        self.phone = phone
        self.password = password
        self.counter = 0
        self.max_images = 10
        self.clf = load(MODEL_PATH) if os.path.exists(MODEL_PATH) else None
        self.finished = False
        self.training_data = []

    def __del__(self):
        if self.video.isOpened():
            self.video.release()

    def get_frame_stream(self):
        while True:
            success, frame = self.video.read()
            if not success:
                break

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(gray, 1.3, 5)

            for (x, y, w, h) in faces:
                face = gray[y:y + h, x:x + w]
                face_resized = cv2.resize(face, (50, 50))

                if self.mode == 'register' and self.counter < self.max_images:
                    # Upload to Cloudinary
                    _, buffer = cv2.imencode('.png', face_resized)
                    img_bytes = BytesIO(buffer)
                    upload_result = cloudinary.uploader.upload(img_bytes, folder=f"faces/{self.name}/")

                    # Save full data to MongoDB
                    faces_collection.insert_one({
                        "name": self.name,
                        "cid": self.cid,
                        "dob": self.dob,
                        "phone": self.phone,
                        "password": self.password,
                        "image_url": upload_result["secure_url"],
                        "timestamp": datetime.now(),
                        "balance": 0  # 🪙 starting balance
                    })

                    # Store for model training
                    self.training_data.append({
                        "img": face_resized,
                        "name": self.name
                    })

                    self.counter += 1

                    # Show progress
                    progress_text = f"Capturing {self.counter}/{self.max_images}"
                    cv2.putText(frame, progress_text, (x, y - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

                    if self.counter == self.max_images:
                        train_model_memory(self.training_data)
                        self.finished = True

                # if self.mode == 'detect' and self.clf:
                #     face_flat = face_resized.flatten().reshape(1, -1)
                #     label = self.clf.predict(face_flat)[0]
                #     cv2.putText(frame, label, (x, y - 10),
                #                 cv2.FONT_HERSHEY_SIMPLEX, 0.9, (36, 255, 12), 2)

                # cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                
                if self.mode == 'detect' and self.clf:
                    face_flat = face_resized.flatten().reshape(1, -1)
                    label = self.clf.predict(face_flat)[0]

                    last_detected_user["userId"] = label  # <-- Store label globally
                    cv2.putText(frame, label, (x, y - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (36, 255, 12), 2)

                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

            if self.mode == 'register' and self.finished:
                self.__del__()
                break

            ret, jpeg = cv2.imencode('.jpg', frame)
            if not ret:
                break

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')

            if self.mode == 'register' and self.finished:
                self.video.release()
                break
