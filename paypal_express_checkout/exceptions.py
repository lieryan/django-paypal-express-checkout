class PaypalExpressException(Exception): 
    def __init__(self, response, *args, **kwargs):
        self.response = response
        super(PaypalExpressException, self).__init__(response.get('L_LONGMESSAGE0', ['Exception when calling Paypal'])[0], *args, **kwargs)

