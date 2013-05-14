class PaypalExpressException(Exception): 
    def __init__(self, response, *args, **kwargs):
        self.response = response
        super(PaypalExpressException, self).__init__(*args, **kwargs)

