import asyncio

import zmq
import msgpack

def main():
    ctx = zmq.Context()
    pupil_remote = zmq.Socket(ctx, zmq.REQ)
    pupil_remote.connect('tcp://127.0.0.1:50020') #using default port (cf. Pupil Remote GUI)

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
    pub_socket = zmq.Socket(ctx, zmq.PUB)
    pub_socket.connect("tcp://127.0.0.1:{}".format(pub_port))

    # Assumes `sub_port` to be set to the current subscription port
    subscriber = ctx.socket(zmq.SUB)
    subscriber.connect(f'tcp://{ip}:{sub_port}')
    subscriber.subscribe('surfaces.')  # receive all gaze messages

    # # Start the annotations plugin
    # notify(
    #     pupil_remote,
    #     {"subject": "start_plugin", "name": "Annotation_Capture", "args": {}},
    # )

    # # Start recording
    # pupil_remote.send_string("R")
    # pupil_remote.recv_string()
    # time.sleep(1.0)  # sleep for a few seconds, can be less

    # # Send annotation
    # my_annotation = create_annotation("helloooo", 1.0, request_pupil_time(pupil_remote))
    # my_annotation["current_condition"] = "Mix2"
    # send_annotation(pub_socket, my_annotation)
    # time.sleep(1.0)  # sleep for a few seconds, can be less

    # ------------------socket.io server--------------------------
    import socketio
    from aiohttp import web

    sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*', async_handlers=True)
    app = web.Application()
    sio.attach(app)

    sendGazeData = True

    #define events
    @sio.event
    def connect(sid, environ, auth):
        print('connection established')

    @sio.event
    def connect_error(data):
        global connected
        connected = False
        print('connection failed')

    @sio.event
    def disconnect(sid):
        stopSendingGazeData()
        print('disconnected')

    @sio.on('startSendingGazeData')
    async def startSendingGazeData(sid):
        print("Start sending gaze data")
        global sendGazeData
        sendGazeData = True
        loop = asyncio.get_event_loop()

        while sendGazeData:
            msg_parts = await loop.run_in_executor(None, subscriber.recv_multipart)

            if len(msg_parts) == 2:
                topic, payload = msg_parts
                data = msgpack.loads(payload, raw=False)

                await sio.emit("gazeData", data)
            else:
                print("Unexpected message format received")

            await asyncio.sleep(1 / 60)  # Send at 60 Hz (adjust this as needed)

    @sio.on('stopSendingGazeData')
    def stopSendingGazeData(sid=None):
        print("stop sending gaze data")
        global sendGazeData
        sendGazeData = False
    
    # def annotateTrialData(trialData):
    #     print("new trial", trialData)
    #     # Send annotation
    #     my_annotation = create_annotation("newTrial", 1.0, request_pupil_time(pupil_remote))
    #     my_annotation["current_condition"] = trialData
    #     send_annotation(pub_socket, my_annotation)
    #     time.sleep(1.0)  # sleep for a few seconds, can be less
    # @sio.on('startTrial', annotateTrialData)

    # convenience function
    def send_recv_notification(n):
        pupil_remote.send_string(f"notify.{n['subject']}", flags=zmq.SNDMORE)
        pupil_remote.send(msgpack.dumps(n))
        return pupil_remote.recv_string()

    @sio.on('calibrate') 
    def calibrate(sid=None):
        #set calibration method
        n = {'subject':'calibration.Monitor', 'args':{}}
        print(send_recv_notification(n))
        pupil_remote.send_string('C') #activate calibration
        print("calibration started")
        print(pupil_remote.recv_string())

    #execute aiohttp application
    if __name__ == '__main__':
        web.run_app(app)

def notify(pupil_remote, notification):
    """Sends ``notification`` to Pupil Remote"""
    topic = "notify." + notification["subject"]
    payload = msgpack.dumps(notification, use_bin_type=True)
    pupil_remote.send_string(topic, flags=zmq.SNDMORE)
    pupil_remote.send(payload)
    return pupil_remote.recv_string()

def create_annotation(label, duration, time):
    return {
        "topic": "annotation",
        "label": label,
        "duration": duration,
        "timestamp": time
    }

def send_annotation(pub_socket, trigger):
    payload = msgpack.dumps(trigger, use_bin_type=True)
    pub_socket.send_string(trigger["topic"], flags=zmq.SNDMORE)
    pub_socket.send(payload)

def request_pupil_time(pupil_remote):
    pupil_remote.send_string("t")
    pupil_time = pupil_remote.recv()
    return float(pupil_time)

if __name__ == "__main__":
    main()