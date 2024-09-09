# Setup
This project uses pdm to manage dependencies. 
You can follow the instructions [here](https://pdm-project.org/latest/) to install pdm.

After installing pdm, you can install the dependencies by running:
```bash
pdm install
```

You'll need to add the .env file to the root of the project. You can use the .env.example as a template.

You'll also need to configure `USER_SERVICE_URL` and `USER_SERVICE_API_KEY` in the .env file.
The values should match the URL and API key of the api service.
The API key is set in the .env file of the api service.

To start the app in development mode do the following:

```bash
# Start the socketio server with live reload
pdm run socketio
```

# Production deploy

The production deploy is done with docker-compose.yaml

You'll need to have .env file, too and also build the docker image first.