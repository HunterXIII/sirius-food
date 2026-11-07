"""Адаптер между HTTP-монолитом и сервисом доставки."""
import logging

import grpc

import delivery_pb2 as pb
import delivery_pb2_grpc as rpc
from app.exceptions import ForbiddenError, NotFoundError


class DeliveryGrpcClient:
    def __init__(self, channel):
        self.stub = rpc.DeliveryServiceStub(channel)

    def assign_courier(self, order_id: int, courier_id: int) -> int:
        request = pb.AssignCourierRequest(order_id=order_id, courier_id=courier_id)
        return self._call(self.stub.AssignCourier, request).delivery_id

    def get_delivery(self, delivery_id: int, current_user) -> dict:
        request = pb.GetDeliveryRequest(delivery_id=delivery_id, user_id=current_user.id)
        response = self._call(self.stub.GetDelivery, request)
        return {
            "id": response.id,
            "order_id": response.order_id,
            "courier_id": response.courier_id or None,
            "status": response.status,
        }

    def complete_delivery(self, delivery_id: int, current_user) -> None:
        request = pb.CompleteDeliveryRequest(delivery_id=delivery_id, user_id=current_user.id)
        self._call(self.stub.CompleteDelivery, request)

    def track_delivery(self, delivery_id: int, user_id: int):
        request = pb.TrackDeliveryRequest(delivery_id=delivery_id, user_id=user_id)
        return self.stub.TrackDelivery(request, timeout=10)

    def chat_with_courier(self, messages, timeout=None):
        requests = (pb.ChatMessage(text=text) for text in messages)
        return self.stub.ChatWithCourier(requests, timeout=timeout)

    @staticmethod
    def _call(method, request):
        try:
            return method(request, timeout=5)
        except grpc.RpcError as error:
            if error.code() == grpc.StatusCode.NOT_FOUND:
                raise NotFoundError(error.details()) from error
            if error.code() == grpc.StatusCode.PERMISSION_DENIED:
                raise ForbiddenError(error.details()) from error
            if error.code() == grpc.StatusCode.FAILED_PRECONDITION:
                raise ValueError(error.details()) from error
            if error.code() == grpc.StatusCode.UNAVAILABLE:
                raise ConnectionError("Сервис доставки недоступен") from error
            if error.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                raise TimeoutError("Сервис доставки не ответил за 5 секунд") from error
            raise


def log_delivery_statuses(delivery_id: int, user_id: int):
    logger = logging.getLogger("uvicorn.error")
    # Фоновая подписка использует свой канал после завершения HTTP-запроса.
    with grpc.insecure_channel("127.0.0.1:50051") as channel:
        client = DeliveryGrpcClient(channel)
        try:
            for response in client.track_delivery(delivery_id, user_id):
                logger.info("Доставка %s: %s", delivery_id, response.status)
        except grpc.RpcError as error:
            logger.error(
                "Ошибка трекинга доставки %s (%s): %s",
                delivery_id, error.code().name, error.details(),
            )
