class PaypalExpressException(Exception): 
    def __init__(self, *args, **kwargs):
        if 'response' in kwargs:
            self.response = kwargs.pop('response')
            message = self.response.get('L_LONGMESSAGE0', ['Exception when calling Paypal.'])[0]
            super(PaypalExpressException, self).__init__(message, *args, **kwargs)
        else:
            super(PaypalExpressException, self).__init__(*args, **kwargs)

