"""Консольная проверка двух видов потоков gRPC."""
import argparse

import grpc

import delivery_pb2 as pb
import delivery_pb2_grpc as rpc


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    track = commands.add_parser("track")
    track.add_argument("delivery_id", type=int)
    track.add_argument("user_id", type=int)
    chat = commands.add_parser("chat")
    chat.add_argument("messages", nargs="+")
    args = parser.parse_args()

    with grpc.insecure_channel("127.0.0.1:50051") as channel:
        stub = rpc.DeliveryServiceStub(channel)
        if args.command == "track":
            request = pb.TrackDeliveryRequest(delivery_id=args.delivery_id, user_id=args.user_id)
            for response in stub.TrackDelivery(request, timeout=10):
                print(response.status, flush=True)
        else:
            messages = (pb.ChatMessage(text=text) for text in args.messages)
            for response in stub.ChatWithCourier(messages, timeout=10):
                print(response.text, flush=True)


if __name__ == "__main__":
    main()
