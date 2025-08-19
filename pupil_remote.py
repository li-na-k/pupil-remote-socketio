import asyncio
from collections import deque
import time
import zmq
import msgpack

from pupil_labs.realtime_api.simple import Device
from pupil_labs.real_time_screen_gaze.gaze_mapper import GazeMapper

sendGazeData  = False
capture_task  = None
process_task  = None

def main():
    print("Pupil remote script started.")
    ip = "192.168.137.183"

    #get device
    global device
    device = Device(address=ip, port="8080")
    print(f"Phone Battery Level: {device.battery_level_percent} %")

    #get GazeMapper object
    calibration = device.get_calibration()
    gaze_mapper = GazeMapper(calibration)
    
    #specify april tags
    marker_verts_mainscreen = {
    0: [ # marker id 0 (top left)
        (15, 15), # Top left marker corner
        (135, 15), # Top right
        (135, 135), # Bottom right
        (15, 135), # Bottom left
    ],
    1: [ # marker id 1 (top right)
        (1785, 15), # Top left marker corner
        (1905, 15), # Top right
        (1905, 135), # Bottom right
        (1785, 135), # Bottom left
    ],
    2: [ # marker id 2 (bottom right)
        (1785, 935), # Top left marker corner
        (1905, 935), # Top right
        (1905, 1055), # Bottom right
        (1785, 1055), # Bottom left
    ],
    3: [ # marker id 3 (bottom left)
        (15, 935), # Top left marker corner
        (135, 935), # Top right
        (135, 1055), # Bottom right
        (15, 1055), # Bottom left
    ]
    }

    marker_verts_secondscreen = {
    4: [ # marker id 4 (top left)
        (15, 15), # Top left marker corner
        (135, 15), # Top right
        (135, 135), # Bottom right
        (15, 135), # Bottom left
    ],
    5: [ # marker id 5 (top right)
        (2425, 15), # Top left marker corner
        (2545, 15), # Top right
        (2545, 135), # Bottom right
        (2425, 135), # Bottom left
    ],
    6: [ # marker id 6 (bottom right)
        (2425, 1205), # Top left marker corner
        (2545, 1205), # Top right
        (2545, 1325), # Bottom right
        (2425, 1325), # Bottom left
    ],
    7: [ # marker id 7 (bottom left)
        (15, 1205), # Top left marker corner
        (135, 1205), # Top right
        (135, 1325), # Bottom right
        (15, 1325), # Bottom left
    ],
    }

    screen_size_mainscreen = (1920, 1200) #right (DELL Laptop)
    screen_size_secondscreen = (1920, 1065) #left (DELL Monitor)


    mainscreen = gaze_mapper.add_surface(
        marker_verts_mainscreen,
        screen_size_mainscreen
    )

    secondscreen = gaze_mapper.add_surface(
        marker_verts_secondscreen,
        screen_size_secondscreen
    )


    # ------------------socket.io server--------------------------
    import socketio
    from aiohttp import web

    sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*', async_handlers=True)
    app = web.Application()
    sio.attach(app)

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
    async def disconnect(sid):
        await stopSendingGazeData()
        print('client disconnected')

    frame_q = asyncio.Queue(maxsize=1)

    async def capture_loop():
        loop = asyncio.get_running_loop()
        while sendGazeData:
            fg = await loop.run_in_executor(None,
                device.receive_matched_scene_video_frame_and_gaze)
            try:
                frame_q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            await frame_q.put(fg)

    async def process_loop():
        frame_cnt, lat_hist = 0, deque(maxlen=30)
        while sendGazeData:
            frame, gaze = await frame_q.get()

            # t0 = time.perf_counter()
            result = gaze_mapper.process_frame(frame, gaze)

            batch = []

            for surf_id, lst in result.mapped_gaze.items():
                for g in lst:
                    if not g.is_on_aoi:
                        continue
                    if surf_id == mainscreen.uid:
                        screen = "mainscreen"
                    elif surf_id == secondscreen.uid:
                        screen = "secondscreen"
                    else:
                        continue
                    batch.append({"norm_pos": [g.x, g.y], "name": screen})

            if batch:
                await sio.emit("gazeData", batch)

            # if len(msg_parts) == 2:
            #     print(".............")
            #     topic, payload = msg_parts
            #     data = msgpack.loads(payload, raw=False)


            #     for surface_gaze in result.mapped_gaze[mainscreen.uid]:
            #         print(f"Gaze at {surface_gaze.x}, {surface_gaze.y}")
            #         msg_parts = [surface_gaze.x, surface_gaze.y]

            #     # Extract only the necessary fields for the frontend
            #     if 'gaze_on_surfaces' in data and len(data['gaze_on_surfaces']) > 0:
            #         gaze_surface = data['gaze_on_surfaces'][0]
            #         if gaze_surface['on_surf']:
            #             optimized_data = {
            #                 'norm_pos': gaze_surface['norm_pos'],
            #                 'name': data['name']
            #             }
            #             # Send only the optimized data to the frontend
            #             await sio.emit("gazeData", optimized_data)
            #             print("data: ", optimized_data)
            # else:
            #     print("Unexpected message format received", msg_parts)
            # lat_hist.append((time.perf_counter() - t0) * 1000)
            # frame_cnt += 1
            # if frame_cnt % 30 == 0:
            #     print(batch)   
            #     print(f"Ø proc-lat last 30: {sum(lat_hist)/len(lat_hist):4.1f} ms")

    @sio.on('startSendingGazeData')
    async def startSendingGazeData(sid):
        global sendGazeData, capture_task, process_task
        if sendGazeData:
            print("Sending gaze data was already running...")
            return
        sendGazeData = True
        capture_task = asyncio.create_task(capture_loop())
        process_task = asyncio.create_task(process_loop())
        print("Start sending gaze data")
  

    @sio.on('stopSendingGazeData')
    async def stopSendingGazeData(sid=None):
        global sendGazeData, capture_task, process_task
        if not sendGazeData:
            return
        print("stop sending gaze data")
        sendGazeData = False
        for t in (capture_task, process_task):
            if t:
                t.cancel()
        await asyncio.gather(capture_task, process_task, return_exceptions=True)
        capture_task = process_task = None
    
    # def annotateTrialData(trialData):
    #     print("new trial", trialData)
    #     # Send annotation
    #     my_annotation = create_annotation("newTrial", 1.0, request_pupil_time(pupil_remote))
    #     my_annotation["current_condition"] = trialData
    #     send_annotation(pub_socket, my_annotation)
    #     time.sleep(1.0)  # sleep for a few seconds, can be less
    # @sio.on('startTrial', annotateTrialData)

    # convenience function
    # def send_recv_notification(n):
    #     pupil_remote.send_string(f"notify.{n['subject']}", flags=zmq.SNDMORE)
    #     pupil_remote.send(msgpack.dumps(n))
    #     return pupil_remote.recv_string()

    # @sio.on('calibrate') 
    # def calibrate(sid=None):
    #     #set calibration method
    #     n = {'subject':'calibration.Monitor', 'args':{}}
    #     print(send_recv_notification(n))
    #     pupil_remote.send_string('C') #activate calibration
    #     print("calibration started")
    #     print(pupil_remote.recv_string())

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