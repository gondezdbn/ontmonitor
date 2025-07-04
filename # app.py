# app.py
# Backend dengan Database, Registrasi, dan Verifikasi Email

# 1. Impor Library
import os
import re
import subprocess
import threading
import time
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_socketio import SocketIO, emit
from flask_mail import Mail, Message
from flask_bcrypt import Bcrypt
from itsdangerous import URLSafeTimedSerializer
from pysnmp.hlapi import *

# 2. Inisialisasi dan Konfigurasi Aplikasi
app = Flask(__name__)
app.config['SECRET_KEY'] = 'kunci-rahasia-yang-sangat-aman-dan-unik-sekali'
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'users.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Konfigurasi Email (WAJIB DIISI DENGAN DATA ANDA)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', 'ganti-dengan-email-anda@gmail.com')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', 'ganti-dengan-app-password-anda')
app.config['MAIL_DEFAULT_SENDER'] = app.config['MAIL_USERNAME']

# Inisialisasi Ekstensi Flask
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
mail = Mail(app)
socketio = SocketIO(app, async_mode='eventlet')
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'
s = URLSafeTimedSerializer(app.config['SECRET_KEY'])


# 3. Model Database
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(60), nullable=False)
    verified = db.Column(db.Boolean, nullable=False, default=False)

    def __repr__(self):
        return f"User('{self.email}')"

# 4. Konfigurasi Flask-Login
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# 5. Fungsi Bantuan (Helpers)
def send_verification_email(user_email):
    """Mengirim email dengan link verifikasi."""
    token = s.dumps(user_email, salt='email-confirm-salt')
    msg = Message('Konfirmasi Email - ONT Monitor', recipients=[user_email])
    link = url_for('confirm_email', token=token, _external=True)
    msg.html = render_template('email/confirm.html', link=link)
    mail.send(msg)

def get_ping_data(ip):
    """Melakukan ping ke IP dan mengembalikan latensi dalam ms."""
    try:
        output = subprocess.check_output(['ping', '-c', '1', '-W', '2', ip], stderr=subprocess.STDOUT, universal_newlines=True)
        match = re.search(r'time=([\d\.]+)\s*ms', output)
        return float(match.group(1)) if match else None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

def get_snmp_data(ip, community, oid):
    """Mengambil data dari perangkat via SNMP."""
    try:
        iterator = getCmd(SnmpEngine(), CommunityData(community, mpModel=0), UdpTransportTarget((ip, 161), timeout=1, retries=3), ContextData(), ObjectType(ObjectIdentity(oid)))
        errorIndication, errorStatus, errorIndex, varBinds = next(iterator)
        if errorIndication or errorStatus: return None
        return varBinds[0][1]
    except Exception:
        return None


# 6. Rute Halaman (Views)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and bcrypt.check_password_hash(user.password_hash, request.form['password']):
            if user.verified:
                login_user(user)
                return redirect(url_for('index'))
            else:
                flash('Akun Anda belum terverifikasi. Silakan cek email Anda.', 'warning')
        else:
            flash('Login gagal. Periksa kembali email dan password Anda.', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        hashed_password = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')
        user = User(email=request.form['email'], password_hash=hashed_password)
        db.session.add(user)
        db.session.commit()
        send_verification_email(user.email)
        flash('Akun berhasil dibuat! Silakan cek email Anda untuk verifikasi.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/confirm_email/<token>')
def confirm_email(token):
    try:
        email = s.loads(token, salt='email-confirm-salt', max_age=3600)
    except:
        flash('Link verifikasi tidak valid atau telah kedaluwarsa.', 'danger')
        return redirect(url_for('login'))
    user = User.query.filter_by(email=email).first_or_404()
    if user.verified:
        flash('Akun sudah terverifikasi. Silakan login.', 'info')
    else:
        user.verified = True
        db.session.commit()
        flash('Email berhasil diverifikasi! Anda sekarang bisa login.', 'success')
    return redirect(url_for('login'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    return render_template('index.html')


# 7. Logika Real-time (SocketIO)
monitor_thread = None
stop_thread = False

def monitoring_loop(ip, community):
    """Thread yang berjalan di background untuk memonitor ONT."""
    global stop_thread
    OID_IF_IN_OCTETS = '1.3.6.1.2.1.2.2.1.10.1'
    OID_IF_OUT_OCTETS = '1.3.6.1.2.1.2.2.1.16.1'
    OID_WIFI_USERS = '1.3.6.1.4.1.2011.5.2.1.15.1.3' # Contoh OID, sesuaikan!
    
    last_in_octets, last_out_octets, last_time = 0, 0, time.time()
    
    # Pengecekan koneksi awal
    if get_ping_data(ip) is None:
        socketio.emit('connect_error', {'message': 'Host tidak dapat dijangkau.'})
        return
    if get_snmp_data(ip, community, '1.3.6.1.2.1.1.1.0') is None:
        socketio.emit('connect_error', {'message': 'Gagal terhubung via SNMP.'})
        return
    socketio.emit('connect_success', {'message': f'Berhasil terhubung ke {ip}.'})

    while not stop_thread:
        current_time = time.time()
        delta_time = current_time - last_time
        download_kbps, upload_kbps = 0, 0
        in_octets = get_snmp_data(ip, community, OID_IF_IN_OCTETS)
        out_octets = get_snmp_data(ip, community, OID_IF_OUT_OCTETS)
        
        if in_octets is not None and out_octets is not None and delta_time > 0:
            current_in_octets, current_out_octets = int(in_octets), int(out_octets)
            if last_in_octets > 0:
                download_kbps = ((current_in_octets - last_in_octets) * 8) / delta_time / 1024
            if last_out_octets > 0:
                upload_kbps = ((current_out_octets - last_out_octets) * 8) / delta_time / 1024
            last_in_octets, last_out_octets = current_in_octets, current_out_octets
            
        ping_ms = get_ping_data(ip)
        user_count = get_snmp_data(ip, community, OID_WIFI_USERS)
        
        socketio.emit('update_data', {
            'download': f"{max(0, download_kbps):.2f}",
            'upload': f"{max(0, upload_kbps):.2f}",
            'ping': f"{ping_ms:.2f}" if ping_ms is not None else "N/A",
            'users': str(user_count) if user_count is not None else "N/A"
        })
        last_time = current_time
        socketio.sleep(2)

@socketio.on('start_monitoring')
def handle_start_monitoring(data):
    global monitor_thread, stop_thread
    ip, community = data.get('ip'), data.get('community', 'public')
    if not ip:
        emit('connect_error', {'message': 'Alamat IP tidak boleh kosong.'})
        return
    if monitor_thread and monitor_thread.is_alive():
        stop_thread = True
        monitor_thread.join()
    stop_thread = False
    monitor_thread = threading.Thread(target=monitoring_loop, args=(ip, community))
    monitor_thread.start()

@socketio.on('stop_monitoring')
def handle_stop_monitoring():
    global stop_thread
    stop_thread = True
    emit('disconnect_status', {'message': 'Monitoring dihentikan.'})

@socketio.on('disconnect')
def handle_disconnect():
    global stop_thread
    stop_thread = True


# 8. Titik Masuk Eksekusi Aplikasi
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    socketio.run(app, debug=True, use_reloader=False)