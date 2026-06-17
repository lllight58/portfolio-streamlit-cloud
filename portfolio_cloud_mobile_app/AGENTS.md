# Codex Working Rule

This app is used from both PC and mobile through Streamlit Cloud.

After any code, schema, dependency, config, or UI change that should affect the app, Codex must deploy the update to Streamlit Cloud before finishing the task:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy_to_streamlit_cloud.ps1 "Describe the change"
```

Mobile app URL:

```text
https://lllight58-portfolio-stream-portfolio-cloud-mobile-appapp-6nltfr.streamlit.app/
```

Local-only verification is not enough. If the user asks for an app change, the work is not complete until the deployment script has pushed the change to GitHub for Streamlit Cloud redeploy.
