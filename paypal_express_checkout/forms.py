"""Forms for the ``paypal_express_checkout`` app."""
import httplib
import logging
import urllib
import urllib2
import urlparse

from django import forms
from django.conf import settings
from django.core.urlresolvers import reverse
from django.http import Http404
from django.shortcuts import redirect
try:
    from django.utils.timezone import now
except ImportError:
    from datetime import datetime
    now = datetime.now
from django.utils.translation import ugettext_lazy as _

from .constants import PAYMENT_STATUS, PAYPAL_DEFAULTS
from .exceptions import PaypalExpressException
from .models import (
    Item,
    PaymentTransaction,
    PaymentTransactionError,
    PurchasedItem,
)
from .settings import API_URL, LOGIN_URL


logger = logging.getLogger(__name__)

class PayPalFormMixin(object):
    """Common methods for the PayPal forms."""
    def call_paypal(self, post_data):
        """
        Gets the PayPal API URL from the settings and posts ``post_data``.

        :param post_data: The full post data for PayPal containing all needed
          information for the current transaction step.

        """
        try:
            response = urllib2.urlopen(
                API_URL, data=urllib.urlencode(post_data))
        except (
                urllib2.HTTPError,
                urllib2.URLError,
                httplib.HTTPException), ex:
            self.log_error(ex)
        else:
            parsed_response = urlparse.parse_qs(response.read())
            return parsed_response

    def get_cancel_url(self):
        """Returns the paypal cancel url."""
        return urlparse.urljoin(settings.HOSTNAME, reverse(
            'paypal_canceled', kwargs=self.get_url_kwargs()))

    def get_error_url(self):
        """Returns the url of the payment error page."""
        return reverse('paypal_error')

    def get_notify_url(self):
        """Returns the notification (ipn) url."""
        return urlparse.urljoin(settings.HOSTNAME, reverse('ipn_listener'))

    def get_return_url(self):
        """Returns the paypal return url."""
        return urlparse.urljoin(settings.HOSTNAME, reverse(
            'paypal_confirm', kwargs=self.get_url_kwargs()))

    def get_success_url(self):
        """Returns the url of the payment success page."""
        return reverse('paypal_success')

    def log_error(self, error_message, transaction=None):
        """
        Saves error information as a ``PaymentTransactionError`` object.

        :param error_message: The message of the exception or response string
          from PayPal.

        """
        payment_error = PaymentTransactionError()
        payment_error.user = self.user
        payment_error.response = error_message
        payment_error.transaction = transaction
        payment_error.save()
        return payment_error


class GetExpressCheckoutDetailsForm(PayPalFormMixin, forms.Form):
    """
    Takes the input from the ``GetExpressCheckoutDetails``, validates it and
    takes care of the PayPal API operations.

    """

    token = forms.CharField()
    
    def __init__(self, user, *args, **kwargs):
        self.user = user
        super(GetExpressCheckoutDetailsForm, self).__init__(*args, **kwargs)
        try:
            self.transaction = PaymentTransaction.objects.get(
                user=user, transaction_id=self.data['token'])
        except PaymentTransaction.DoesNotExist:
            raise Http404

    def get_post_data(self):
        """Creates the post data dictionary to send to PayPal."""
        post_data = dict(PAYPAL_DEFAULTS)
        post_data.update({
            'METHOD': 'GetExpressCheckoutDetails',
            'TOKEN': self.transaction.transaction_id,
        })
        return post_data

    def get_details(self):
        post_data = self.get_post_data()
        parsed_response = self.call_paypal(post_data)
        if parsed_response.get('ACK')[0] == 'Success':
            return parsed_response
        elif parsed_response.get('ACK')[0] == 'Failure':
            self.log_error(parsed_response, self.transaction)
            raise PaypalExpressException(parsed_response)

class DoExpressCheckoutForm(PayPalFormMixin, forms.Form):
    """
    Takes the input from the ``DoExpressCheckoutView``, validates it and
    takes care of the PayPal API operations.

    """
    token = forms.CharField()

    payerID = forms.CharField()

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super(DoExpressCheckoutForm, self).__init__(*args, **kwargs)
        try:
            self.transaction = PaymentTransaction.objects.get(
                user=user, transaction_id=self.data['token'])
        except PaymentTransaction.DoesNotExist:
            raise Http404

    def get_post_data(self):
        """Creates the post data dictionary to send to PayPal."""
        post_data = dict(PAYPAL_DEFAULTS)
        post_data.update({
            'METHOD': 'DoExpressCheckoutPayment',
            'TOKEN': self.transaction.transaction_id,
            'PAYERID': self.data['payerID'],
            'PAYMENTREQUEST_0_AMT': self.transaction.value,
            'PAYMENTREQUEST_0_NOTIFYURL': self.get_notify_url(),
        })
        return post_data

    def do_checkout(self):
        """Calls PayPal to make the 'DoExpressCheckoutPayment' procedure."""
        post_data = self.get_post_data()
        parsed_response = self.call_paypal(post_data)
        if parsed_response.get('ACK')[0] == 'Success':
            transaction_id = parsed_response.get(
                'PAYMENTINFO_0_TRANSACTIONID')[0]
            self.transaction.transaction_id = transaction_id
            self.transaction.status = PAYMENT_STATUS['pending']
            self.transaction.save()
            return redirect(self.get_success_url())
        elif parsed_response.get('ACK')[0] == 'Failure':
            self.transaction.status = PAYMENT_STATUS['canceled']
            self.transaction.save()
            self.log_error(parsed_response, self.transaction)
            return redirect(self.get_error_url())


class SetExpressCheckoutFormMixin(PayPalFormMixin):
    """
    Base form class for all forms invoking the ``SetExpressCheckout`` PayPal
    API operation, providing the general method skeleton.

    Also this is to be used to construct custom forms.

    """
    def __init__(self, user, *args, **kwargs):
        self.user = user
        super(SetExpressCheckoutFormMixin, self).__init__(*args, **kwargs)

    def get_content_object(self):
        """
        Can be overridden to return a different content object for the
        PaymentTransaction model.

        This is useful if you want e.g. have one of your models assigned to the
        transaction for easier identification.

        """
        # TODO for now it should return the user, although I know, that the
        # user is already present in the user field of the PaymentTransaction
        # model.
        # Maybe we can remove the user field safely in exchange for the generic
        # relation only.
        return self.user

    def get_item(self):
        """Obsolete. Just implement ``get_items_and_quantities``."""
        raise NotImplemented

    def get_quantity(self):
        """Obsolete. Just implement ``get_items_and_quantities``."""
        raise NotImplemented

    def get_items_and_quantities(self):
        """
        Returns the items and quantities.

        Should return a list of tuples: ``[(item, quantity), ]``

        """
        logger.warning(
            'Deprecation warning: Please implement get_items_and_quantities on'
            ' your SetExpressCheckoutForm. Do not use get_item and'
            ' get_quantity any more.')
        return [(self.get_item(), self.get_quantity()), ]

    def get_post_data(self, item_quantity_list):
        """Creates the post data dictionary to send to PayPal."""
        post_data = dict(PAYPAL_DEFAULTS)
        total_value = 0
        item_index = 0
        for item, quantity in item_quantity_list:
            if not quantity:
                # If a user chose quantity 0, we don't include it
                continue
            total_value += item.value * quantity
            post_data.update({
                'L_PAYMENTREQUEST_0_NAME{0}'.format(
                    item_index): item.name,
                'L_PAYMENTREQUEST_0_DESC{0}'.format(
                    item_index): item.description,
                'L_PAYMENTREQUEST_0_AMT{0}'.format(
                    item_index): item.value,
                'L_PAYMENTREQUEST_0_QTY{0}'.format(
                    item_index): quantity,
            })
            item_index += 1

        post_data.update({
            'METHOD': 'SetExpressCheckout',
            'PAYMENTREQUEST_0_AMT': total_value,
            'PAYMENTREQUEST_0_ITEMAMT': total_value,
            'RETURNURL': self.get_return_url(),
            'CANCELURL': self.get_cancel_url(),
        })
        return post_data

    def get_url_kwargs(self):
        """Provide additional url kwargs, by overriding this method."""
        return {}

    def post_transaction_save(self, transaction, item_quantity_list):
        """
        Override this method if you need to create further objects.

        Once we got a successful response from PayPal we can create a
        Transaction with status "checkout". You might want to create or
        manipulate further objects in your app at this point.

        For example you might ask for user's the t-shirt size on your checkout
        form. This a good place to save the user's choice on the UserProfile.

        """
        return

    def process_set_checkout(self):
        """
        Calls PayPal to make the 'SetExpressCheckout' procedure.

        :param items: A list of ``Item`` objects.

        """
        item_quantity_list = self.get_items_and_quantities()
        post_data = self.get_post_data(item_quantity_list)

        # making the post to paypal and handling the results
        parsed_response = self.call_paypal(post_data)
        if parsed_response.get('ACK')[0] == 'Success':
            token = parsed_response.get('TOKEN')[0]
            transaction = PaymentTransaction(
                user=self.user,
                date=now(),
                transaction_id=token,
                value=post_data['PAYMENTREQUEST_0_AMT'],
                status=PAYMENT_STATUS['checkout'],
                content_object=self.get_content_object(),
            )
            transaction.save()
            self.post_transaction_save(transaction, item_quantity_list)
            for item, quantity in item_quantity_list:
                if not quantity:
                    continue
                item_kwargs = {
                    'user': self.user,
                    'transaction': transaction,
                    'quantity': quantity,
                }
                if item.pk:
                    item_kwargs.update({'item': item, })
                PurchasedItem.objects.create(**item_kwargs)
            return transaction
        self.log_error(parsed_response)
        raise PaypalExpressException(response=parsed_response)
    def set_checkout(self):
        """
        Calls PayPal to make the 'SetExpressCheckout' procedure.

        :param items: A list of ``Item`` objects.

        """
        try:
            transaction = self.process_set_checkout()
            token = transaction.transaction_id
            return redirect(LOGIN_URL + token)
        except PaypalExpressException as e:
            parsed_response = e.response 
            return redirect(self.get_error_url())

class SetExpressCheckoutItemForm(SetExpressCheckoutFormMixin, forms.Form):
    """
    Takes the input from the ``SetExpressCheckoutView``, validates it and
    takes care of the PayPal API operations.

    """
    item = forms.ModelChoiceField(
        queryset=Item.objects.all(),
        empty_label=None,
        label=_('Item'),
    )

    quantity = forms.IntegerField(
        label=_('Quantity'),
    )

    def get_item(self):
        """Keeping this for backwards compatibility."""
        return self.cleaned_data.get('item')

    def get_quantity(self):
        """Keeping this for backwards compatibility."""
        return self.cleaned_data.get('quantity')

    def get_items_and_quantities(self):
        """
        Returns the items and quantities.

        Should return a list of tuples.

        """
        return [
            (self.get_item(), self.get_quantity()),
        ]
