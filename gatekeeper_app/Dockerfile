FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# 1. Install system prerequisites
RUN apt-get update && apt-get install -y \
    curl \
    git \
    unzip \
    xz-utils \
    zip \
    libglu1-mesa \
    openjdk-17-jdk \
    wget \
    && rm -rf /var/lib/apt/lists/*

# 2. Environment variables
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV ANDROID_HOME=/opt/android-sdk
ENV FLUTTER_HOME=/opt/flutter
ENV PATH="${PATH}:${FLUTTER_HOME}/bin:${ANDROID_HOME}/cmdline-tools/latest/bin:${ANDROID_HOME}/platform-tools"

# 3. Android SDK Setup
RUN mkdir -p ${ANDROID_HOME}/cmdline-tools \
    && wget -q https://dl.google.com/android/repository/commandlinetools-linux-9477386_latest.zip -O /tmp/cmdline-tools.zip \
    && unzip -q /tmp/cmdline-tools.zip -d /tmp/cmdline-tools \
    && mkdir -p ${ANDROID_HOME}/cmdline-tools/latest \
    && mv /tmp/cmdline-tools/cmdline-tools/* ${ANDROID_HOME}/cmdline-tools/latest/ \
    && rm -rf /tmp/cmdline-tools /tmp/cmdline-tools.zip

# Accept licenses & install SDK components
RUN yes | sdkmanager --sdk_root=${ANDROID_HOME} --licenses \
    && sdkmanager --sdk_root=${ANDROID_HOME} \
       "platform-tools" \
       "platforms;android-33" \
       "platforms;android-34" \
       "platforms;android-35" \
       "platforms;android-36" \
       "build-tools;33.0.2" \
       "build-tools;35.0.0" \
       "ndk;28.2.13676358" \
       "cmake;3.22.1"

# Release signing is fail-closed in build.gradle.kts. Supply key.properties
# through the CI secret mount; this image never creates or substitutes a debug key.

# 4. Flutter SDK Setup
RUN git clone -b stable https://github.com/flutter/flutter.git ${FLUTTER_HOME} \
    && git config --global --add safe.directory ${FLUTTER_HOME} \
    && flutter precache \
    && flutter doctor

# 5. Workspace directory
WORKDIR /workspace
