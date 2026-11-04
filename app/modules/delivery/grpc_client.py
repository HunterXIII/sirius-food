"""Адаптер между HTTP-монолитом и сервисом доставки."""
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
            "courier_id": response.courier_id,
            "status": response.status,
        }

    def complete_delivery(self, delivery_id: int, current_user) -> None:
        request = pb.CompleteDeliveryRequest(delivery_id=delivery_id, user_id=current_user.id)
        self._call(self.stub.CompleteDelivery, request)

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
