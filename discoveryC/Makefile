CC=go
TARGET=discoveryC
FLAGS=-ldflags '-w'
CWD=$(shell pwd)

default: $(TARGET)

check:
	$(CC) test -v ./

$(TARGET):
	#CGO_ENABLED=0 GOOS=linux $(CC) build $(FLAGS) -o $(TARGET)
	$(CC) build $(FLAGS) -o $(TARGET)

run: $(TARGET)
	./$(TARGET)

godep:
	go get -u github.com/tools/godep

restore: $(GODEP)
	godep restore

clean:
	$(RM) $(TARGET)

re: clean $(TARGET)
