FROM python:3.13.18-slim-trixie
ENV LINTVOICE_RULES_DIR=/opt/lintvoice/rules
RUN --mount=type=bind,source=dist,target=/dist pip install --no-cache-dir /dist/*.whl && lintvoice rules install && pip uninstall -y -q pip
COPY LICENSE THIRD_PARTY_NOTICES.md third_party/licenses /usr/share/doc/lintvoice/
USER 10001
WORKDIR /work
ENTRYPOINT ["lintvoice"]
