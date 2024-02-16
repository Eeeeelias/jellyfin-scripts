import subprocess
import time
import requests
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv('API_KEY')
jellyfin_ip = os.getenv('JELLYFIN_IP')
wakeup_time = os.getenv('WAKEUP_TIME')

client = 'ShutdownScript'
device = 'ShutdownScript'
VERSION = '1.0.0'
headers = {'Authorization': f'MediaBrowser Client="{client}", Device="{device}",'
                            f'Version="{VERSION}", Token="{api_key}"'}


def send_message():
    sessions = requests.get(f"{jellyfin_ip}/Sessions?ActiveWithinSeconds=300", headers=headers)
    session_data = sessions.json()
    active_sessions = 0
    session_ids = []
    time_to_shutdown = 0
    longest_session = ""
    for i in session_data:
        try:
            if i['PlayState']['PositionTicks'] > 0:
                curr_tick_pos = i['PlayState']['PositionTicks']
                episode_ticks = i['NowPlayingItem']['RunTimeTicks']
                tmp = episode_ticks - curr_tick_pos
                if tmp > time_to_shutdown:
                    time_to_shutdown = tmp
                    longest_session = i['Id']
        except KeyError:
            pass
        session_ids.append(i['Id'])
        active_sessions += 1
    info1 = {"Text": f"[INFO] The server will shut down after your episode finished", "TimeoutMS": 5000}
    info2 = {"Text": f"[INFO] The server will shut down in {int(time_to_shutdown / 600000000)} minutes.", "TimeoutMS": 5000}
    for i in session_ids:
        try:
            message = info1 if i == longest_session else info2
            requests.post(f"{jellyfin_ip}/Sessions/{i}/Message", headers=headers, json=message)
        except KeyError:
            continue
    print(f"Messaged {active_sessions} session(s)!")
    return int(time_to_shutdown / 600000000) + 1

print(wakeup_time)
minutes_left = send_message()
print(f'Shutting down in {minutes_left} minutes')
time.sleep(minutes_left * 60)
print("Shutting down now!")

if wakeup_time:
    subprocess.run(['rtcwake', '-l', '--date', f'{wakeup_time}', '-m', 'mem'])
else:
    # put the computer to sleep, so it can be woken up by WOL
    subprocess.run(['systemctl', 'suspend'])