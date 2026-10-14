# Build context is the repository root:  docker build -f lambda/Dockerfile .
FROM public.ecr.aws/lambda/python:3.14

COPY lambda/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY lcsh_validator/ ${LAMBDA_TASK_ROOT}/lcsh_validator/
COPY rules/ ${LAMBDA_TASK_ROOT}/rules/
COPY data/derived/lcsh.sqlite data/derived/rules.sqlite data/derived/name_cache.sqlite \
     data/derived/free_floating_subdivisions.json ${LAMBDA_TASK_ROOT}/data/derived/
COPY lambda/handler.py ${LAMBDA_TASK_ROOT}/handler.py

CMD ["handler.handler"]
