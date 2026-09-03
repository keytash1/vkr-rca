FROM golang:1.26-alpine AS build

WORKDIR /src

COPY go.mod go.sum ./
RUN go mod download
COPY cmd ./cmd
COPY internal ./internal

ARG SERVICE
RUN test -n "${SERVICE}" && \
    CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/service "./cmd/${SERVICE}"

FROM alpine:3.23

RUN apk add --no-cache ca-certificates && \
    addgroup -S app && \
    adduser -S -G app app

COPY --from=build /out/service /usr/local/bin/service

USER app
ENTRYPOINT ["/usr/local/bin/service"]
