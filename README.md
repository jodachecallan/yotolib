# YotoLib

YotoLib is a free, open-source app that backs up the Yoto cards you own. Paste a card's link, and YotoLib saves its audio, cover art, and track list to a library you can browse and play in the browser. A zip copy goes to a separate backup folder, and the library can be copied to Google Drive. It runs on Windows, macOS, and Linux, in Docker, and on Kubernetes. Only back up cards you legally own, or cards you have permission to keep a copy of.

**Website:** [jodachecallan.github.io/yotolib](https://jodachecallan.github.io/yotolib/)

YotoLib is an independent project. It is not affiliated with, endorsed by, or sponsored by Yoto.

## Getting Started

[Releases](https://github.com/jodachecallan/yotolib/releases) include a built app for Windows, macOS, and Linux. No Python install is required. Closing the console window stops the app. Each release is also published as a Docker image, `ghcr.io/jodachecallan/yotolib`, for amd64 and arm64. See [Docker](#docker) and [Kubernetes](#kubernetes).

## Screenshots

![Home](docs/images/home.png)

![Add cards](docs/images/add-cards.png)

![Settings](docs/images/settings.png)

## Setup

Requires Python 3.12.

```bash
git clone https://github.com/jodachecallan/yotolib.git
cd yotolib
python3 -m venv venv
```

Activate the virtual environment:

```bash
source venv/bin/activate
```

On Windows:

```bash
venv\Scripts\activate
```

Then install the dependencies:

```bash
pip install -r requirements.txt
```

## Run

```bash
python yotolib.py
```

The app binds to `127.0.0.1`, starting at port 8765, and opens in your browser. Closing the terminal stops it. `YOTOLIB_HOST`, `YOTOLIB_PORT`, `YOTOLIB_OPEN_BROWSER`, and `YOTOLIB_DATA_DIR` override the bind address, port, browser, and the folder used for `config.json`, the library, and backups. `YOTOLIB_ALLOWED_HOSTS` is a comma-separated list of host names the app answers to, such as `yotolib.lan,*.home.lan`. It defaults to `localhost`, `127.0.0.1`, and `[::1]`, plus `YOTOLIB_HOST` when that is a specific address. Requests that use any other name are refused, which stops websites from reaching the app through DNS rebinding. Changes sent from another website, such as starting a backup or signing out, are refused as well.

## Usage

1. In **Settings**, set a library folder and a different backup folder. The defaults are `library/` and `backups/` next to the app.
2. Read the card URL with the NXP TagInfo app ([App Store](https://apps.apple.com/es/app/nfc-taginfo-by-nxp/id1246143596), [Google Play](https://play.google.com/store/apps/details?id=com.nxp.taginfolite)): Scan & Launch, then hold the card to the phone.
3. In **Add cards**, paste one or more Yoto card links (`https://yoto.io/...`), one per line. Other links are refused. Card artwork and audio are downloaded only over https from public addresses. Confirm that you legally own the cards, or have permission to keep a copy, then download. The full terms are in **Settings**.
4. Each card is stored as `library/<card id>/` with `card.json`, the cover, `audio/`, and `images/`. A dated zip of that folder is written to the backup folder. Pasting a card that is already in the library skips it. Check **Replace cards already in the library** to download it again, replace the library folder, and write a new zip.
5. `backups/recovery.json` stores the card id, title, and URL for every card saved, including cards whose library folder was later removed. Use that list to download the library again.

## Google Drive backup

From **Cloud backup**, you can copy the library to a folder in your Google Drive. The backup runs only when you start it.

1. In Google Cloud Console, create a project and enable the Google Drive API. Configure the OAuth consent screen with the scope `https://www.googleapis.com/auth/drive.file`. Add your Google account as a test user, or publish the app.
2. Create an OAuth client ID of type **TVs and Limited Input devices**. In **Cloud backup**, open **Google Drive setup**, paste the client id and secret, name the Drive folder (the default is `YotoLib backups`), and save. On Kubernetes you can put `YOTOLIB_GOOGLE_CLIENT_ID` and `YOTOLIB_GOOGLE_CLIENT_SECRET` in the `yotolib-google-oauth` secret instead.
3. Choose **Sign in with Google**. A Google window opens at `google.com/device`. Enter the code that the page shows, then allow access. The page then shows that you are signed in.
4. Choose **Back up now**. Each card is zipped and uploaded as `<category> - <title>[<card id>].zip`, followed by `recovery.json`. On later backups, cards that have not changed are skipped, and changed cards replace their earlier zip.

Sign-in uses Google's device code flow, so the app works over plain `http://` on your LAN. Google does not allow its redirect sign-in on an http address other than localhost. The sign-in is kept in memory only. Restarting the app or the pod signs you out, and **Sign out** revokes the token. The `drive.file` scope lets the app see only files it created, so the backup folder must be one that YotoLib made.

## Docker

```bash
docker run --rm -p 8765:8765 -v yotolib-data:/data ghcr.io/jodachecallan/yotolib:latest
```

Open `http://localhost:8765`. The named volume `yotolib-data` keeps the library between runs. Use a release tag such as `v2.1.0` instead of `latest` to stay on one version. To build the image yourself, run `docker build -t yotolib:local .` and use `yotolib:local`.

- To keep the data in a folder on your computer instead, the container user (uid 1000) needs write access to it. Use `-v "$PWD/data:/data" --user "$(id -u):$(id -g)"`, or run `chown -R 1000:1000 data` first. Docker creates a missing folder owned by root, and the app stops with a message that says so.
- To open the app by another name or by the computer's LAN address, add that name or address to the allowed hosts, for example `-e YOTOLIB_ALLOWED_HOSTS=localhost,192.168.1.20`. Otherwise the page answers `This host name is not allowed`.

## Kubernetes

The manifests use Kustomize. [deploy/k8s/base](deploy/k8s/base) holds the generic resources: a namespace, a volume claim, the Deployment, Service, Ingress, and a NetworkPolicy. Your own values go in an overlay. `deploy/k8s/overlays/local/` is in `.gitignore`, so your host names stay on your machine.

The container listens on `0.0.0.0:8765` and does not open a browser. `config.json`, the library, and backups are kept on a persistent volume at `/data`.

Keep the Ingress hostname on your LAN. The app has no login, and anyone who can open it can use the library and start a Drive backup while you are signed in.

1. Copy the example overlay:

   ```bash
   cp -r deploy/k8s/overlays/example deploy/k8s/overlays/local
   ```

2. In `deploy/k8s/overlays/local/kustomization.yaml`:
   - Set `newTag` to the release you want to run.
   - Replace `yotolib.example.lan` with your LAN DNS name in both places: `YOTOLIB_ALLOWED_HOSTS` and the Ingress host.
   - If the cluster has no default Ingress class or StorageClass, or the library needs more than 10Gi, uncomment the matching patch.

   If audio playback stops at the proxy timeout, raise that timeout on your Ingress.
3. Optionally, store the Google client in a secret:

   ```bash
   kubectl create namespace yotolib
   kubectl -n yotolib create secret generic yotolib-google-oauth \
     --from-literal=YOTOLIB_GOOGLE_CLIENT_ID=... \
     --from-literal=YOTOLIB_GOOGLE_CLIENT_SECRET=...
   ```

4. Preview and apply:

   ```bash
   kubectl kustomize deploy/k8s/overlays/local
   kubectl apply -k deploy/k8s/overlays/local
   ```

   Everything is created in the `yotolib` namespace. Check the pod with `kubectl -n yotolib get pods`.

The NetworkPolicy lets the pod reach only cluster DNS and public https addresses, so it cannot reach other cluster services or your LAN. Your CNI must support NetworkPolicy (Calico, Cilium, or k3s). Plain flannel ignores it.

To run an image you built yourself, push it to a registry your cluster can pull from, and set `newName` next to `newTag` in your overlay.

## Releasing

[CI](.github/workflows/ci.yml) runs on every branch push and pull request. It starts the app and checks its responses, validates the Kubernetes manifests, lints the workflows, and builds the Docker image for amd64 and arm64. Nothing is published.

[Release](.github/workflows/release.yml) publishes the executables and the `ghcr.io/jodachecallan/yotolib` image. It runs only for a `v*` tag on `main`. Merge to `main`, then tag the merge commit:

```bash
git checkout main && git pull
git tag -a v2.2.0 -m "Release notes"
git push origin v2.2.0
```

A tag on any other branch stops at the `verify-tag` step without publishing.

## License

The application is MIT. See [LICENSE](LICENSE).

That license covers this program and its documentation. It does not cover Yoto card audio, covers, or other content the app downloads. The fonts in `static/fonts/` are under the [SIL Open Font License](static/fonts/OFL.txt).