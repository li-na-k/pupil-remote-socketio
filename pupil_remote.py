from time import sleep
import zmq
import msgpack

ctx = zmq.Context()
pupil_remote = zmq.Socket(ctx, zmq.REQ)
pupil_remote.connect('tcp://127.0.0.1:50020') #using default port (cf. Pupil Remote GUI)
# pupil_remote.send_string('C') #activate calibration

# ------------------ connect to ipc backbone ---------
# The REQ talks to Pupil remote and receives the session unique IPC SUB PORT
pupil_remote = ctx.socket(zmq.REQ)

ip = 'localhost'  # If you talk to a different machine use its IP.
port = 50020  # The port defaults to 50020. Set in Pupil Capture GUI.

pupil_remote.connect(f'tcp://{ip}:{port}')

# Request 'SUB_PORT' for reading data
pupil_remote.send_string('SUB_PORT')
sub_port = pupil_remote.recv_string()

# Request 'PUB_PORT' for writing data
pupil_remote.send_string('PUB_PORT')
pub_port = pupil_remote.recv_string()

# Assumes `sub_port` to be set to the current subscription port
subscriber = ctx.socket(zmq.SUB)
subscriber.connect(f'tcp://{ip}:{sub_port}')
subscriber.subscribe('gaze.')  # receive all gaze messages

# ------------------socket.io server--------------------------
import socketio
from aiohttp import web

sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')
app = web.Application()
sio.attach(app)

#define events
@sio.event
def connect(sid, environ, auth): #invoked automatically when a client connects to the server
    print('connection established')

sendGazeData = True

@sio.on('startSendingGazeData')
async def startSendingGazeData(sid):
  print("start sending gaze data")
  global sendGazeData
  sendGazeData = True
  while sendGazeData:
    sleep(0.1)
    topic, payload = subscriber.recv_multipart()
    data = msgpack.loads(payload, raw=False)
    # print(f"{message}") #[b'norm_pos'], message[b'gaze_point_3d']
    await sio.emit("gazeData", data)

@sio.on('stopSendingGazeData')
def stopSendingGazeData(sid):
   print("stop sending gaze data")
   global sendGazeData
   sendGazeData = False

#execute aiohttp application
if __name__ == '__main__':
    web.run_app(app)

