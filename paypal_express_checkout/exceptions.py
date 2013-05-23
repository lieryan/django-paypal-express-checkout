class PaypalExpressException(Exception): 
    def __init__(self, *args, **kwargs):
        if 'response' in kwargs:
            self.response = kwargs['response']
            message = self.response.get('L_LONGMESSAGE0', ['Exception when calling Paypal.'])[0]
            super(PaypalExpressException, self).__init__(message=message, *args, **kwargs)
        else:
            super(PaypalExpressException, self).__init__(*args, **kwargs)

