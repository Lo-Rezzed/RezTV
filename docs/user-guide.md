# RezTV User Guide

## First Login

1. Open your admin panel: `https://yourdomain.com/admin`
2. You will be asked for a username and password (the `ADMIN_USERNAME` and `ADMIN_PASSWORD` you set in your `.env` file)
3. After logging in you will see the admin dashboard

## Setting Your Station Name

1. At the top of the admin page, enter your desired Station Name
2. Click **Save Station Name**
3. This name will appear on the public landing page and in the video player

## Uploading Videos

1. Go to the **Upload Video** section
2. Select a video file
3. Optionally type a folder name (or pick an existing one). Leave it blank and the video goes in **Unsorted**
4. Click **Upload**. A progress bar will show the upload status
5. After uploading, the video appears in the Media Library under its folder

## Media Folders

- The **Folders** list on the left of the Media Library shows every folder and how many videos it holds. Click one to see only those videos, or **All media** to see everything
- To move a video, click **Move** next to it and type the folder name. Typing a new name creates that folder
- Folder names can use letters, numbers, spaces, `-` and `_`. Anything else is removed
- New uploads are stored on the server under `media/<folder name>/`. Moving a video only changes its folder in the admin panel; the file stays where it is, so a channel that is playing it is not interrupted
- Videos uploaded before folders existed are shown in **Unsorted** and keep working

## Creating a Channel

1. Go to the **Create Channel** section
2. Enter a name for the channel
3. Click **Create Channel**
4. The new channel will also appear on the public landing page

## Adding Videos to a Channel

1. In the Media Library, use the dropdown next to a video
2. Select the channel you want
3. Click **Add**

To add a whole folder at once:

1. Click the folder in the **Folders** list
2. In the bar above the videos, choose a channel and click **Add Folder to Channel**
3. Every video in that folder is added to the end of the channel. Videos already in the channel are skipped

## Removing a Video from a Channel

- In the Channels section, click **Remove** next to a video
- This only takes it off that channel. It stays in the Media Library and in any other channels
- To delete a video from the server completely, use the red **Delete** button in the Media Library instead

## Reordering Videos

- In the Channels section, drag and drop videos to change the play order
- The new order is saved automatically

**Note:** a running channel keeps playing its old list. After adding, removing or reordering videos, click **Stop Stream** and then **Start Stream** to apply the changes.

## Starting a Channel

1. Find the channel in the Channels section
2. Click **Start Stream**
3. Wait a few seconds, then open the channel page or the public player

## Public Pages

- Landing page: `https://yourdomain.com`
- Channel player: `https://yourdomain.com/channel/1` (replace 1 with the channel ID)

## Editing or Deleting

- You can rename a channel with the **Edit Name** button
- You can delete videos or entire channels with the red **Delete** buttons
