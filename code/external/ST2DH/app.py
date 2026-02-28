from datetime import datetime
from email import message
from enum import Enum
import json
import stripe

# Our stuff
import dhservices
from dhs_logging import logger
from config import config

from flask import Flask, jsonify, request

app = Flask(__name__)

###############################################################################
## Deep Harbor Stuff
###############################################################################

def update_membership(member):
    def get_member_id_from_email(access_token, email):
        # This function will return the member ID from our database based 
        # on their email address, and we can use it to update their 
        # membership status
        return dhservices.get_member_id(access_token, email)

    # This function will update the member's connections in our database 
    # with their Stripe customer ID, so we can easily look them up in the future    
    def update_connections(access_token):
        existing_connections = dhservices.get_member_connections(access_token, member.id)
        if existing_connections:
            logger.info(f"Current connections for member ID: {member.id}: {existing_connections}")
            existing_connections["stripe_id"] = member.stripe_customer_id
            dhservices.update_member_connections(access_token, member.id, existing_connections)
        else:
            dhservices.update_member_connections(access_token, member.id, {"stripe_id": member.stripe_customer_id})
    
    # This function will update the member's membership status in our database 
    # based on the information we got from Stripe
    def update_membership_status(access_token):        
        current_status = dhservices.get_member_status(access_token, member.id)
        logger.info(f"Current membership status for member ID: {member.id}: {current_status}")
        # We want to set the membership level to the name of the product they 
        # subscribed to in Deep Harbor
        current_status["membership_level"] = member.dh_product_name
        # And we need to hold onto the subscription ID and product ID from Stripe in the membership status in Deep Harbor,
        # so we can use it later if we need to.
        current_status["stripe_subscription_id"] = member.stripe_subscription_id
        current_status["stripe_product_id"] = member.stripe_product_id
        
        # Okay, we need to determine how to set their membership. Here's the logic:
        # If their current membership is set to Inactive *only*, and they're subscribing to a product, 
        # then we set them to Active.
        # Anything else and we set them to Inactive. 
        # Lemme explain a little more: If the member status is "Pending", then that's
        # great because they want to be a member, but we don't want to set them to "Active"
        # until they are _explicitly_ set to Active by someone using the DH admin site.
        # If they're marked as "Inactive", it's because they _were_ a member before and are
        # trying to rejoin. 
        # There could be other types of status, including "Banned", which means we don't want
        # them to be able to be a member at all, so we don't want to change the status of 
        # someone who's "Banned" to "Active" just because they subscribed to a product in 
        # Stripe, that would be bad.
        
        # For sanity checking, let's convert the current membership status to lowercase so we can 
        # compare it more easily, and also log it for debugging purposes.
        membership_status = current_status["membership_status"].lower()
        logger.debug(f"Member ID: {member.id} current membership status (lowercase): {membership_status}")
         
        logger.debug(f"Determining how to update membership status for member ID: {member.id} based on current status: {membership_status} and Stripe event membership status: {member.membership_status}")        
       
        # Do we need to update anything? - This is explicitly set below
        # for sanity checking and to make it clear that in some cases we want to 
        # update the membership information, but we don't want to change their 
        # membership status because it's already correct, so we still want to update 
        # the membership level and other info, but we don't want to accidentally 
        # set them to inactive just because they subscribed to a product in Stripe again.
        update_information = False
        if membership_status == "inactive" and member.membership_status == MembershipStatus.ACTIVE:
            update_information = True
            current_status["membership_status"] = "active"
            logger.debug(f"Member ID: {member.id} is currently Inactive and subscribing to a product in Stripe, setting membership status to Active")
        elif membership_status == "active" and member.membership_status == MembershipStatus.ACTIVE:
            # Do *NOT* update the membership status, because they're already active, 
            # but we do want to update the membership level and other info, which will 
            # happen later in this function.
            update_information = False 
            # Active stays active if they subscribe to a product in Stripe again, we just want to make 
            # sure we update their membership level and other info, but we don't want to accidentally 
            # set them to inactive just because they subscribed to a product in Stripe again.
            current_status["membership_status"] = "active"
            logger.debug(f"Member ID: {member.id} is currently Active and subscribing to a product in Stripe, keeping membership status as Active")
        elif membership_status == "pending" and member.membership_status == MembershipStatus.ACTIVE:
            update_information = True
            # Pending stays pending until someone manually approves them in the DH admin 
            # site, even if they subscribe to a product in Stripe.
            current_status["membership_status"] = "pending"
            logger.debug(f"Member ID: {member.id} is currently Pending and subscribing to a product in Stripe, keeping membership status as Pending")
        else:
            update_information = True
            # Everything else we set them to Inactive, regardless of the situation
            current_status["membership_status"] = "inactive"
            logger.debug(f"Member ID: {member.id} is currently {current_status['membership_status']} and subscribing (or unsubscribing) to a product in Stripe, setting membership status to Inactive")
        
        # If they're already active, we don't need to do anything, but if they're not active, 
        # then we need to update their membership status in our database to reflect 
        # that they're not active anymore.
        if update_information == False:
            logger.info(f"Member ID: {member.id} is active, no need to update membership status in DHService")
            return
        
        logger.info(f"Updating membership status for member ID: {member.id} to {current_status}")
        dhservices.update_member_status(access_token, member.id, current_status)

    # This function will get the notes for the member and add a new note 
    # about the Stripe event that just happened for the member, so we 
    # have a record of it.    
    def update_notes(access_token):
        subscription_status = "Subscribed to" if member.membership_status == MembershipStatus.ACTIVE else "Unsubscribed from"
        # Convert the next billing date from a timestamp to a human-readable date
        if member.next_billing_date is not None:
            member.next_billing_date = datetime.fromtimestamp(member.next_billing_date).strftime("%Y-%m-%d")
        notes_data = {
                "note": f"Stripe event: {subscription_status} for product {member.dh_product_name}. Next billing date: {member.next_billing_date}",
                "from": "ST2DH",
                "timestamp": datetime.now().isoformat()
            }        
            
        logger.info(f"Adding note to member ID: {member.id} with content: {notes_data}")    
        dhservices.update_member_notes(access_token, member.id, notes_data)
    
    
    # This is where we would call the Deep Harbor API to update the member's
    # membership status based on the information we got from Stripe. 
    # For now, we'll just log it.
    logger.info(f"Updating membership for {member.email_address} to {member.membership_status.name}")
    logger.info(f"Next billing date: {member.next_billing_date}")
    logger.info(f"Stripe Customer ID: {member.stripe_customer_id}")
    logger.info(f"Stripe Subscription ID: {member.stripe_subscription_id}")
    logger.info(f"Stripe Product ID: {member.stripe_product_id}")
    logger.info(f"Deep Harbor Product Name: {member.dh_product_name}")
    
    # For use in all the following API calls, we need to get an access token from our DHService API using the client credentials flow
    access_token = dhservices.get_access_token(config["dh_services"]["client_name"], 
                                               config["dh_services"]["client_secret"])

    # First we need to get the member ID from our database based on their email address
    member.id = get_member_id_from_email(access_token, member.email_address)
    logger.info(f"Got member ID: {member.id} for email address: {member.email_address}")
    # Sanity check that we got a member ID back, if not we can't update their membership status
    if member.id is None:
        logger.error(f"Could not find member ID for email address: {member.email_address}, cannot update membership status")
        return
    
    # Store the Stripe customer ID in the member's connections in our database, 
    update_connections(access_token)
    
    # Now we can update their membership info. Note that the field
    # is status, but here we're only going to be updating the
    # *product* that is in Deep Harbor, based on the Stripe product.
    update_membership_status(access_token)
    
    # Then we update the note for the member
    update_notes(access_token)


###############################################################################
## S T R I P E  S T U F F
###############################################################################

# This is the only place we need to set the API key, 
# so we do it here at the top of the file 'cause why not
stripe.api_key = config["stripe"]["api_key"]

# It's pretty simple, you're either a member, or you ain't
class MembershipStatus(Enum):
    ACTIVE = (1,)
    INACTIVE = (2,)

# This is the class that represents a member and has all the
# information we need to update their status from Stripe
# (some of this was taken from the previous version of the code,
# "ST2WA")
class Member:
    def __init__(
        self,
        id,
        email_address,
        stripe_customer_id,
        stripe_subscription_id,
        stripe_product_id,
        dh_product_name,
        membership_status,
        next_billing_date=None,
    ):
        self.id = id
        self.email_address = email_address
        self.membership_status = membership_status
        self.next_billing_date = next_billing_date
        self.stripe_customer_id = stripe_customer_id
        self.stripe_subscription_id = stripe_subscription_id
        self.stripe_product_id = stripe_product_id
        self.dh_product_name = dh_product_name
    def __str__(self) -> str:
        return (
            f"Member ID: {self.id}\n"
            f"Email: {self.email_address}\n"
            f"Membership Status: {self.membership_status}\n"
            f"Next Billing Date: {self.next_billing_date}\n"
            f"Stripe Customer ID: {self.stripe_customer_id}\n"
            f"Stripe Subscription ID: {self.stripe_subscription_id}\n"
            f"Stripe Product ID: {self.stripe_product_id}\n"
            f"Deep Harbor Product Name: {self.dh_product_name}"
        )

# This function will parse the subscription object from Stripe 
# and return the membership level and email address
def handle_message(stripe_event):
    # This function will return the name and email address of a customer 
    # based on their Stripe ID if they still exist in Stripe. 
    def get_email_address_from(customer_id):
        customer = stripe.Customer.retrieve(customer_id)
        if customer.get("deleted"):
            logger.warning(f"Customer with ID {customer_id} has been deleted in Stripe, cannot get email address")
            return None, None
        # They're still a customer in Stripe, so we can get their email address and name
        return (
            customer["name"],
            customer["email"],
        )
    # This function will return the name and email address of a customer
    # based on their Stripe ID if they have been deleted in Stripe, which means we can't 
    # get their email address from Stripe, but we can look them up in our database based 
    # on their Stripe customer ID
    def find_email_address_from_stripe_customer_id(customer_id):
        access_token = dhservices.get_access_token(config["dh_services"]["client_name"], config["dh_services"]["client_secret"])
        member = dhservices.get_member_by_stripe_customer_id(access_token, customer_id)
        if member is None:
            logger.error(f"Could not find member with Stripe customer ID: {customer_id} in our database, cannot get email address")
            return None, None
        return f"{member['identity']['first_name']} {member['identity']['last_name']}", member['identity']['primary_email']
    
    def get_dh_products():
        # This function will return a list of products from our database, 
        # and we can use it to match the Stripe product ID to the 
        # membership level in Deep Harbor
        access_token = dhservices.get_access_token(config["dh_services"]["client_name"], config["dh_services"]["client_secret"])
        return dhservices.get_products(access_token)

    # Okay, so if we're here, we got a subscription event where the person is either
    # creating a new subscription (yay!) or deleting an existing one (boo!)
    # As far as we're concerned in this function, we don't care about the difference
    # between the two, as later on the Deep Harbor function will handle it.
    logger.info(f"Got a subscription event: {stripe_event.type}")

    # First thing we need is to convert the message into a dictionary
    subscription_event = stripe_event.data.object

    # The JSON is different for different types of events, so we need 
    # to check which one we got and if we don't care about it right now
    # then we'll just note that and return without doing anything else. 
    # We only care about subscription creation, update, and deletion 
    # events right now, but we could easily add more if we wanted to.
    if stripe_event.type == "customer.subscription.created":
        logger.info("It's a subscription creation event")
    elif stripe_event.type == "customer.subscription.updated":
        logger.info("It's a subscription update event")
    elif stripe_event.type == "customer.subscription.deleted":
        logger.info("It's a subscription deletion event")
    else:
        logger.warning(f"Received an event we don't care about: {stripe_event.type}")
        return

    # Next, we need to get the email address of the person who's subscribing because
    # that's how we identify them in Deep Harbor    
    name, email = get_email_address_from(stripe_event.data.object.customer)
    if email is None:
        # Huh, okay, we couldn't find an email address for this customer, which
        # means they deleted their account in Stripe. That kinda sucks, 'cause we
        # have to work a little harder to find them in our database, but we can still do it based on their Stripe customer ID, so let's do that.
        logger.warning(f"Could not find email address for customer ID: {stripe_event.data.object.customer}, they may have deleted their account in Stripe. Gonna try to find them in our database based on their Stripe customer ID.")
        name, email = find_email_address_from_stripe_customer_id(stripe_event.data.object.customer)
        # If we still can't find an email address for this customer, then we can't update their membership status, so we'll just log that and return.
        if email is None:
            logger.error(f"Could not find email address for customer ID: {stripe_event.data.object.customer} in our database either, cannot update membership status")
            return
    else:
        logger.info(f"We've got a subscription event for {name} ({email})")

    # And put together our Member object
    member = Member(
        id=None,
        email_address=email,
        membership_status=None,
        next_billing_date=None,
        stripe_customer_id=subscription_event.customer,
        stripe_subscription_id=None,
        dh_product_name=None,
        stripe_product_id=None,
    )

    # What product are they subscribing to? This will be used to determine 
    # their membership level
    product_id = stripe_event.data.object["items"]["data"][0]["price"]["product"]
    # Now get the list of products from our database and find the one that matches the Stripe product ID
    dh_products = get_dh_products()
    logger.debug(f"Got the following products from DHService: {dh_products}")
    matching_product = next((p for p in dh_products if p["details"]["stripe_product_id"] == product_id), None)
    if matching_product is None:
        logger.warning(f"Received a subscription event for a product we don't recognize: {product_id}")
        return
    logger.info(f"DH product: {matching_product['name']} (ID: {matching_product['product_id']})")
    member.dh_product_name = matching_product["name"]
    
    # The type of message we got determines whether the member is active
    # or not
    if stripe_event.type == "customer.subscription.created":
        logger.info(f"They're subscribing to Stripe product ID: {product_id}")
        logger.info(f"Updating {name} ({email}) to active")
        # We also want to get the next billing date
        member.next_billing_date = stripe_event.data.object["current_period_end"]
        member.membership_status = MembershipStatus.ACTIVE
        member.stripe_subscription_id = stripe_event.data.object["id"]
        member.stripe_product_id = stripe_event.data.object["items"]["data"][0][
            "price"
        ]["product"]
        # And send it on to DHService to handle the update
        update_membership(member)
    elif stripe_event.type == "customer.subscription.updated":
        logger.info(f"They're subscribing to Stripe product ID: {product_id}")
        logger.info(f"Updating {name} ({email}) to active")
        # We also want to get the next billing date
        member.next_billing_date = stripe_event.data.object["current_period_end"]
        member.membership_status = MembershipStatus.ACTIVE
        member.stripe_subscription_id = stripe_event.data.object["id"]
        member.stripe_product_id = stripe_event.data.object["items"]["data"][0][
            "price"
        ]["product"]
        # And send it on to DHService to handle the update
        update_membership(member)
    elif stripe_event.type == "customer.subscription.deleted":
        logger.info(f"They're unsubscribing from Stripe product ID: {product_id}")
        logger.info(f"Updating {name} ({email}) to inactive")
        member.membership_status = MembershipStatus.INACTIVE
        # And send it on to DHService to handle the update
        update_membership(member)
    else:
        # We shouldn't get here because we already checked for the event type above        
        logger.warning(f"Received an event we don't care about: {stripe_event.type}")       


###############################################################################
# Health check endpoint
###############################################################################

@app.route("/health")
def health():
    return "OK", 200


###############################################################################
# Our webhook that Stripe will call when an event occurs
###############################################################################

@app.route("/webhook", methods=["POST"])
def webhook():
    event = None
    payload = request.data
    sig_header = request.headers["STRIPE_SIGNATURE"]

    # Did we get a valid event from Stripe?
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, config["stripe"]["signing_secret"])
    except ValueError as e:
        # Invalid payload
        logger.error(f"Invalid payload: {e}")        
        raise e
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        logger.error(f"Invalid signature: {e}")        
        raise e

    # Send the event data to our DHService API to save it in our database
    try:
        access_token = dhservices.get_access_token(config["dh_services"]["client_name"], config["dh_services"]["client_secret"])
        dhservices.save_stripe_data(access_token, event)
    except Exception as e:
        logger.error(f"Error saving Stripe data to DHService: {e}")
        raise e

    # If we got here, we have a valid event and we've saved it to our database, 
    # so we can handle it now and work with the member that it correlates with.
    try:
        handle_message(event)
    except Exception as e:
        logger.error(f"HEY! THERE WAS AN ERROR WHEN HANDLING A STRIPE EVENT: {e} - event data: {event} ")
        raise e

    # We're sending this back to Stripe to let them know we got the 
    # message and everything is fine
    return jsonify(success=True)
