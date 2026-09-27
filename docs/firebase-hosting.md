# Firebase Hosting: public browser demo

Firebase Hosting on the no-cost **Spark** plan serves the static files in
`firebase-demo/`. The dashboard simulates jobs in the visitor's browser and
stores them in that browser's local storage. The real FastAPI, PostgreSQL,
Redis, scheduler, and workers remain in this repository and can be run locally
with Docker. Firebase Hosting does not run those backend processes. The demo
is visibly labeled so visitors understand what they are trying.

## Deploy on Windows

1. In the [Firebase console](https://console.firebase.google.com/), create a
   project and leave it on the **Spark (no-cost)** plan. Note its **Project ID**.
   You don't need to enable Firestore, Cloud Functions, or App Hosting.
2. Install [Node.js LTS](https://nodejs.org/) if needed. Open PowerShell in
   `C:\Documents\QueueMaster` and install the Firebase CLI:

   ```powershell
   npm install -g firebase-tools
   firebase login
   ```

3. Deploy only Hosting from the project root. Replace the placeholder with
   the exact Project ID from your Firebase console:

   ```powershell
   firebase deploy --only hosting --project YOUR_PROJECT_ID
   ```

4. Open the `https://YOUR_PROJECT_ID.web.app` URL in the CLI output. Submit a
   Fibonacci job, wait for it to complete, and open its details. Add this link
   to your GitHub README after verifying it in a private browser window.

The repository already includes `firebase.json`. Do not run `firebase init`
and overwrite its `public` setting: it must point at `firebase-demo`.

For later updates: pull the latest repository version, then rerun the same
`firebase deploy --only hosting --project YOUR_PROJECT_ID` command.

Browser data belongs to each visitor; jobs are not shared across computers.
Jobs execute only while that visitor's browser tab is open. The real engine is
documented in the main README and runs with Docker on your computer.
