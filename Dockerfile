#FROM google/cloud-sdk
FROM ubuntu

ENV PYTHONPATH $PYTHONPATH:/usr/lib/google-cloud-sdk/platform/google_appengine
# NOTE: the Cloud SDK component manager is disabled in this install, so
# `gcloud components install app-engine-python` does not work. So, use:
RUN apt-get update && apt-get install -y wget
# RUN apt-get install -y google-cloud-sdk-app-engine-python
WORKDIR /data
RUN wget https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-sdk-277.0.0-linux-x86_64.tar.gz
WORKDIR /usr/local/
RUN tar -xf /data/google-cloud-sdk-277.0.0-linux-x86_64.tar.gz
RUN apt-get install -y python3-pip
COPY test_requirements.txt /
RUN pip3 install -r /test_requirements.txt
RUN pip3 install coveralls
RUN pip3 install django==1.2 jinja2==2.6
RUN apt-get install -y vim
COPY . /workspace
