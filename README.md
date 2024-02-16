# jellyfin-scripts
A small collection of scripts to work with jellyfin.

To run this, you need to have a jellyfin api key, you can create one in `Dashboard` -> `Advanced` -> `API Keys`.

Next, install the requirements with `pip install -r requirements.txt`. 
It might make sense to use a virtual environment for this.

Finally, copy the `.example.env` to `.env` and fill in the required information.

Then you can run the scripts with `python3 <script>.py`.

## Scripts
- `jellyfin_music.py` - A script that creates a random playlist based on what you have listened to recently. It encourages finding new music.


These scripts can be run as a cronjob, based on your needs.