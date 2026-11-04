"""Отдельный процесс, выполняющий бизнес-операции доставки."""
from concurrent import futures
from contextlib import contextmanager
from threading import Lock
from time import sleep
from types import SimpleNamespace

import grpc

import delivery_pb2 as pb
import delivery_pb2_grpc as rpc
from app.database import SessionLocal
from app.exceptions import AccessDeniedError, ForbiddenError, NotFoundError
from app.modules.delivery.repository import PostgresDeliveryRepository
from app.modules.delivery.service import DeliveryService


@contextmanager
def delivery_service(context):
    with SessionLocal() as db:
        try:
            yield DeliveryService(PostgresDeliveryRepository(db))
        except NotFoundError as error:
            context.abort(grpc.StatusCode.NOT_FOUND, str(error))
        except (AccessDeniedError, ForbiddenError) as error:
            context.abort(grpc.StatusCode.PERMISSION_DENIED, str(error))
        except ValueError as error:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(error))


class DeliveryServicer(rpc.DeliveryServiceServicer):
    def __init__(self):
        # В одном процессе проверки и записи назначений выполняются последовательно.
        self.write_lock = Lock()

    def AssignCourier(self, request, context):
        with self.write_lock, delivery_service(context) as service:
            delivery_id = service.assign_courier(request.order_id, request.courier_id)
        print(f"AssignCourier: order_id={request.order_id}, delivery_id={delivery_id}", flush=True)
        return pb.AssignCourierResponse(delivery_id=delivery_id, status="in_progress")

    def CompleteDelivery(self, request, context):
        with self.write_lock, delivery_service(context) as service:
            service.complete_delivery(request.delivery_id, SimpleNamespace(id=request.user_id))
        return pb.CompleteDeliveryResponse(status="completed")

    def GetDelivery(self, request, context):
        with delivery_service(context) as service:
            delivery_id = request.delivery_id
            if request.HasField("order_id"):
                delivery = service.repository.get_delivery_by_order_id(request.order_id)
                if delivery is None:
                    raise NotFoundError("Доставка не найдена")
                delivery_id = delivery.id

            delivery = service.get_delivery(delivery_id, SimpleNamespace(id=request.user_id))
            return pb.GetDeliveryResponse(
                id=delivery.id,
                order_id=delivery.order_id,
                courier_id=delivery.courier_id,
                status=delivery.status,
            )

    def TrackDelivery(self, request, context):
        with delivery_service(context) as service:
            service.get_delivery(request.delivery_id, SimpleNamespace(id=request.user_id))

        # Учебный поток статусов не изменяет запись в базе.
        yield pb.DeliveryStatus(status="in_progress")
        for status in ("on_the_way", "delivered"):
            sleep(2)
            if not context.is_active():
                return
            yield pb.DeliveryStatus(status=status)

    def ChatWithCourier(self, request_iterator, context):
        for message in request_iterator:
            yield pb.ChatMessage(text=f"Курьер получил сообщение: {message.text}")


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    rpc.add_DeliveryServiceServicer_to_server(DeliveryServicer(), server)
    server.add_insecure_port("127.0.0.1:50051")
    server.start()
    print("Delivery gRPC Server running on port 50051", flush=True)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(0).wait()


if __name__ == "__main__":
    serve()
