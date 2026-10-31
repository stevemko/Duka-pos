from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class LoginThrottle(AnonRateThrottle):
    scope = "login"


class CheckoutThrottle(UserRateThrottle):
    scope = "checkout"


class StkPushThrottle(UserRateThrottle):
    scope = "stk_push"


class PaymentThrottle(UserRateThrottle):
    scope = "payment"
