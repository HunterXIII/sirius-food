"""Трекинг доставки и интерактивный чат через gRPC-клиент монолита."""
import argparse
from queue import Queue

import grpc

from app.modules.delivery.grpc_client import DeliveryGrpcClient


def interactive_chat(client):
    messages = Queue()
    # Один двунаправленный RPC остаётся открытым на всё время чата.
    responses = client.chat_with_courier(iter(messages.get, None))
    print("Чат с курьером. Для выхода введите /exit.")
    try:
        while True:
            try:
                text = input("Вы: ")
            except (EOFError, KeyboardInterrupt):
                break
            if text == "/exit":
                break
            if not text.strip():
                continue
            messages.put(text)
            # Следующее сообщение вводим только после ответа на предыдущее.
            print(next(responses).text, flush=True)
    finally:
        messages.put(None)
        responses.cancel()


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    track = commands.add_parser("track")
    track.add_argument("delivery_id", type=int)
    track.add_argument("user_id", type=int)
    chat = commands.add_parser("chat")
    chat.add_argument("messages", nargs="*")
    args = parser.parse_args()

    try:
        with grpc.insecure_channel("127.0.0.1:50051") as channel:
            client = DeliveryGrpcClient(channel)
            if args.command == "track":
                for response in client.track_delivery(args.delivery_id, args.user_id):
                    print(response.status, flush=True)
            elif args.messages:
                for response in client.chat_with_courier(args.messages, timeout=10):
                    print(response.text, flush=True)
            else:
                interactive_chat(client)
    except grpc.RpcError as error:
        parser.exit(1, f"Ошибка gRPC ({error.code().name}): {error.details()}\n")


if __name__ == "__main__":
    main()
