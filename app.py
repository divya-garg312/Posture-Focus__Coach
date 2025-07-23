import cv2
import time
import numpy as np
import mediapipe as mp
from flask import Flask, render_template, Response, jsonify
from math import atan2, degrees, sqrt

posture_status = "good"
total_focus_time = 0
posture_alerts_count = 0
focus_alerts_count = 0
monitoring_active = True
snooze_until = 0

app = Flask(__name__)


mp_drawing = mp.solutions.drawing_utils
mp_pose = mp.solutions.pose
mp_face_mesh = mp.solutions.face_mesh
pose = mp_pose.Pose(min_detection_confidence=0.8, min_tracking_confidence=0.8)
face_mesh = mp_face_mesh.FaceMesh(min_detection_confidence=0.5, min_tracking_confidence=0.5)

# Tracking variables
start_eye_contact_time = None
last_posture_alert_time = 0
last_eye_alert_time = 0
current_alert = "none"
alert_active = False
good_posture_duration = 0
bad_posture_duration = 0

# Constants
POSTURE_ALERT_INTERVAL = 30  # seconds
EYE_ALERT_INTERVAL = 1200     # 30 minutes in seconds
POSTURE_CHECK_INTERVAL = 3    # seconds
SLOUCH_THRESHOLD = 25         # degrees neck angle
SHOULDER_SLOUCH_THRESHOLD = 0.15  # shoulder-ear distance ratio
MIN_FACE_VISIBILITY = 0.6     # minimum face visibility for eye contact
last_posture_check = 0

def calculate_posture_metrics(landmarks):
    """Calculate multiple posture metrics for more robust detection"""
    metrics = {}
    
    # 1. Neck angle (forward lean)
    nose = landmarks[mp_pose.PoseLandmark.NOSE]
    left_ear = landmarks[mp_pose.PoseLandmark.LEFT_EAR]
    right_ear = landmarks[mp_pose.PoseLandmark.RIGHT_EAR]
    left_shoulder = landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER]
    right_shoulder = landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER]
    
    # Mid points
    ear_midpoint = ((left_ear.x + right_ear.x)/2, (left_ear.y + right_ear.y)/2)
    shoulder_midpoint = ((left_shoulder.x + right_shoulder.x)/2, 
                        (left_shoulder.y + right_shoulder.y)/2)
    
    # Neck angle
    dx = ear_midpoint[0] - shoulder_midpoint[0]
    dy = ear_midpoint[1] - shoulder_midpoint[1]
    angle = degrees(atan2(dy, dx))
    metrics['neck_angle'] = 90 - angle
    
    # 2. Shoulder slouch (distance between shoulders and ears)
    left_dist = sqrt((left_shoulder.x - left_ear.x)**2 + (left_shoulder.y - left_ear.y)**2)
    right_dist = sqrt((right_shoulder.x - right_ear.x)**2 + (right_shoulder.y - right_ear.y)**2)
    avg_dist = (left_dist + right_dist) / 2
    metrics['shoulder_slouch'] = avg_dist
    
    # 3. Shoulder asymmetry
    shoulder_diff = abs(left_shoulder.y - right_shoulder.y)
    metrics['shoulder_asymmetry'] = shoulder_diff
    
    return metrics

def detect_face_orientation(face_landmarks, frame_shape):
    """Detect if face is oriented toward screen"""
    if not face_landmarks:
        return False
    
    # Get key facial landmarks
    nose_tip = face_landmarks.landmark[4]  # Nose tip
    left_eye = face_landmarks.landmark[33]  # Left eye inner corner
    right_eye = face_landmarks.landmark[263]  # Right eye inner corner
    
    # Calculate eye midpoint
    eye_mid_x = (left_eye.x + right_eye.x) / 2
    eye_mid_y = (left_eye.y + right_eye.y) / 2
    
    # Check if eyes are in the center of the frame (simple approach)
    frame_center_x = frame_shape[1] / 2
    frame_center_y = frame_shape[0] / 2
    
    # Calculate distance from center
    dist_x = abs(eye_mid_x * frame_shape[1] - frame_center_x)
    dist_y = abs(eye_mid_y * frame_shape[0] - frame_center_y)
    
    # Normalize distances
    norm_dist_x = dist_x / frame_shape[1]
    norm_dist_y = dist_y / frame_shape[0]
    
    # Face is considered oriented toward screen if within 30% of center
    return norm_dist_x < 0.3 and norm_dist_y < 0.3

def detect_posture_and_ergonomics(frame):
    global start_eye_contact_time, last_posture_alert_time, last_eye_alert_time
    global current_alert, alert_active, last_posture_check
    global good_posture_duration, bad_posture_duration
    global posture_status, total_focus_time, posture_alerts_count, focus_alerts_count
    global monitoring_active, snooze_until
    
    if not monitoring_active:
        cv2.putText(frame, "Monitoring Paused", (frame.shape[1]//2 - 100, frame.shape[0]//2), 
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        return frame, False, False
        
    current_time = time.time()
    if current_time < snooze_until:
        cv2.putText(frame, f"Alerts snoozed: {int(snooze_until - current_time)}s remaining", 
                   (50, frame.shape[0] - 50), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 165, 0), 2)
        return frame, False, False
    
    image_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    pose_results = pose.process(image_rgb)
    face_results = face_mesh.process(image_rgb)
    
    frame_has_pose = False
    is_facing_screen = False
    
    
    
    # Posture detection
    if pose_results.pose_landmarks:
        frame_has_pose = True
        landmarks = pose_results.pose_landmarks.landmark
        
        # Posture check (only do this periodically)
        if current_time - last_posture_check > POSTURE_CHECK_INTERVAL:
            last_posture_check = current_time
            metrics = calculate_posture_metrics(landmarks)
            
            # Check for multiple posture issues
            posture_issues = []
            
            # 1. Forward neck lean
            if metrics['neck_angle'] > SLOUCH_THRESHOLD:
                posture_issues.append(f"neck leaning forward ({int(metrics['neck_angle'])}°)")
            
            # 2. Shoulder slouch (shoulders too close to ears)
            if metrics['shoulder_slouch'] < SHOULDER_SLOUCH_THRESHOLD:
                posture_issues.append("slouched shoulders")
            
            # 3. Asymmetrical shoulders
            if metrics['shoulder_asymmetry'] > 0.1:
                posture_issues.append("uneven shoulders")
            
            # Trigger alert if any posture issues detected
            if posture_issues:
                bad_posture_duration += POSTURE_CHECK_INTERVAL
                good_posture_duration = max(0, good_posture_duration - POSTURE_CHECK_INTERVAL/2)
                
                if (current_time - last_posture_alert_time > POSTURE_ALERT_INTERVAL and 
                    bad_posture_duration > 10):  # Only alert after 10s of bad posture
                    current_alert = f"⚠️ Posture alert: {', '.join(posture_issues)}. Please adjust your posture."
                    last_posture_alert_time = current_time
                    alert_active = True
                    posture_alerts_count += 1
            else:
                good_posture_duration += POSTURE_CHECK_INTERVAL
                bad_posture_duration = max(0, bad_posture_duration - POSTURE_CHECK_INTERVAL)
        
        mp_drawing.draw_landmarks(frame, pose_results.pose_landmarks, mp_pose.POSE_CONNECTIONS)
    
    # Eye contact detection (using face orientation)
    is_facing_screen = detect_face_orientation(face_results.multi_face_landmarks[0] if face_results.multi_face_landmarks else None, frame.shape)
    
    if is_facing_screen:
        if start_eye_contact_time is None:
            start_eye_contact_time = current_time
        else:
            duration = current_time - start_eye_contact_time
            total_focus_time = duration
            if duration > EYE_ALERT_INTERVAL and current_time - last_eye_alert_time > EYE_ALERT_INTERVAL:
                current_alert = "🧠 Take a break! You've been focused on the screen for 30 minutes."
                last_eye_alert_time = current_time
                alert_active = True
                focus_alerts_count += 1
                start_eye_contact_time = current_time  # Reset timer
    else:
        # Reset eye contact timer if not facing screen
        start_eye_contact_time = None
    
    # Display posture metrics on frame
    if pose_results.pose_landmarks:
        metrics = calculate_posture_metrics(pose_results.pose_landmarks.landmark)
        cv2.putText(frame, f"Neck angle: {int(metrics['neck_angle'])}°", (20, 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(frame, f"Shoulder slouch: {metrics['shoulder_slouch']:.2f}", (20, 60), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    
    # Display current alert on frame
    if alert_active:
        cv2.putText(frame, current_alert, (50, frame.shape[0] - 50), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    
    return frame, frame_has_pose, is_facing_screen

def generate_frames():
    cap = cv2.VideoCapture(0)
    
    while True:
        success, frame = cap.read()
        if not success:
            break
        
        frame = cv2.flip(frame, 1)
        processed_frame, _, _ = detect_posture_and_ergonomics(frame)
        
        ret, buffer = cv2.imencode('.jpg', processed_frame)
        frame = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/get_stats')
def get_stats():
    return jsonify({
        "posture_status": posture_status,
        "focus_time": int(total_focus_time),
        "posture_alerts": posture_alerts_count,
        "focus_alerts": focus_alerts_count
    })
    
@app.route('/alert_status')
def alert_status():
    global current_alert, alert_active
    alert_to_send = current_alert if alert_active else "none"
    alert_active = False  # Mark alert as handled
    return jsonify({"alert": alert_to_send})

@app.route('/start_monitoring')
def start_monitoring():
    global monitoring_active, snooze_until
    monitoring_active = True
    snooze_until = 0
    return jsonify({"status": "monitoring started"})

@app.route('/snooze_alerts')
def snooze_alerts():
    global snooze_until
    snooze_until = time.time() + 300  # Snooze for 5 minutes (300 seconds)
    return jsonify({"status": "alerts snoozed", "snooze_until": snooze_until})

@app.route('/pause_monitoring')
def pause_monitoring():
    global monitoring_active, start_eye_contact_time, last_posture_check
    monitoring_active = False
    start_eye_contact_time = None  # Reset focus timer
    last_posture_check = 0  # Reset posture check timer
    return jsonify({"status": "monitoring paused"})

@app.route('/get_monitoring_status')
def get_monitoring_status():
    global monitoring_active, snooze_until
    return jsonify({
        "monitoring_active": monitoring_active,
        "snooze_active": time.time() < snooze_until
    })

if __name__ == '__main__':
    app.run(debug=True)