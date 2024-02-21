FROM python:3.10-slim
WORKDIR /app

# install PDM
RUN pip install -U pip setuptools wheel
RUN pip install pdm==2.12.3

COPY pyproject.toml pdm.lock ./
RUN pdm install --prod --no-lock --no-editable

COPY . .

ENTRYPOINT ["./entrypoint.sh"]
