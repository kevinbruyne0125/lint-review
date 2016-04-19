FROM python:2.7
ENV REFRESHED_AT 2016-04-19
RUN apt-get upgrade -y && apt-get update && \
    apt-get install -y php-pear ruby npm && \
    apt-get install -y ruby1.9.1 ruby-dev build-essential && \
    apt-get -y autoremove && apt-get -y clean
RUN pear install PHP_CodeSniffer
RUN npm install -y csslint jshint jscs
RUN ln -s /usr/bin/nodejs /usr/bin/node
WORKDIR /code
ADD . /code
RUN cp /code/settings.sample.py /code/settings.py
RUN pip install -r requirements.txt && pip install .
RUN gem install bundler && bundle install --system
