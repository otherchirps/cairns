# -*- coding: utf-8 -*-
import scrapy
from calendar import monthrange
from datetime import datetime, date
from urlparse import urljoin
from urllib import quote

from ..items import DevelopmentApplicationItem

class PlanningalertsSpider(scrapy.Spider):
    name = "planningalerts"
    allowed_domains = ["eservices.cairns.qld.gov.au"]

    # NOTE: Need to hit this daEnquiryInit link first, since the
    #   webapp sets up its server-side session state at this point.
    #   Trying to fetch any direct pages without this fails miserably. :(
    SEARCH_URL = 'https://eservices.cairns.qld.gov.au/eservice/daEnquiryInit.do?nodeNum=227'

    # From the "how to have your say" page, at:
    # http://www.cairns.qld.gov.au/building-planning-business/-planning/applications/have-your-say
    FEEDBACK_URL = 'mailto:townplanner@cairns.qld.gov.au'

    start_urls = (
        SEARCH_URL,
    )

    display_to_item_fieldmap = {
        'Reference No.': 'council_reference',
        'Date Lodged': 'date_received',
        'Property Details': 'address',
        'Description of Work': 'description',
        'File Reference': 'external_reference'
    }

    def _get_date_range(self):
        # Emulating the form on the website, allowing history searches
        # of a month at a time. Can set other ranges, but if it's too
        # wide, it'll choke and give us nothing, instead of just
        # coughing up a reasonable default.
        today = date.today()
        max_day = monthrange(today.year, today.month)[1]
        return (
            date(today.year, today.month, 1),
            date(today.year, today.month, max_day)
        )

    def _get_comment_url(self, council_reference):
        return "{0}?subject={1}".format(
            self.FEEDBACK_URL,
            quote("Development Application Enquiry: " + council_reference)
        )

    def parse(self, response):
        """ Main entry point of the scraper.  After hitting the
        magic search page, and the session state set up for us,
        we can now run a search form submit, and get some applications.
        """
        first_day, last_day = self._get_date_range()

        self.log("Searching for requests between {} and {}".format(
            first_day, last_day
        ), level=scrapy.log.INFO)

        return scrapy.FormRequest.from_response(
            response,
            formname="daEnquiryForm",
            formdata={
                'dateFrom': first_day.strftime('%d/%m/%Y'),
                'dateTo': last_day.strftime('%d/%m/%Y'),
                'lodgeRangeType': 'on',
                'searchMode': 'A'
            },
            callback=self.parse_search_results
        )

    def parse_search_results(self, response):
        """ Walk the list of development applications, and
        fetch its details page.
        """
        problems = (
            "Problem Encountered",
            "Error Page Exception"
        )
        for problem in problems:
            if problem in response.body:
                self.log("Search form submit failed", level=scrapy.log.ERROR)
                return

        for application in response.xpath('//a[@class="plain_header"]/@href').extract():
            application_url = urljoin(response.url, application)
            yield scrapy.Request(application_url, callback=self.parse_application)

    def parse_application(self, response):
        """ Finally have an application page to look at.
        """
        result = DevelopmentApplicationItem()

        for field in response.xpath('//p[@class="rowDataOnly"]'):
            field_name = field.xpath('.//span[@class="key"]/text()').extract()
            if not field_name:
                continue

            field_name = self.display_to_item_fieldmap.get(field_name[0].strip(), None)
            if field_name:

                if field_name == 'address':
                    # Wow. Looks like someone forced a google map link into the
                    # markup, and make this Civica stuff even *more* finicky to crawl.
                    # For addresses, they've replaced the text with a ul>li>a. Later, at render time,
                    # this (for some reason) gets moved in the DOM to be a sibling element of the result <p>.
                    # But, we don't have to worry about that - hasn't happened at point of scraping.
                    address = field.xpath(".//a/text()").extract()
                    if not address:
                        continue
                    address[0] = address[0].replace(' (map location)', '')
                    field_value = address
                else:
                    field_value = field.xpath('.//span[@class="inputField"]/text()').extract()
                if field_value:
                    result[field_name] = field_value[0].strip()
            else:
                continue

        result['date_scraped'] = date.today().isoformat()
        result['date_received'] = datetime.strptime(
            result['date_received'], '%d/%m/%Y'
        ).date().isoformat()

        # Damn. Site keeps all identifiers hidden in the session.
        # So can't provide direct link to item...
        result['info_url'] = self.SEARCH_URL
        result['comment_url'] = self._get_comment_url(result['council_reference'])

        return result



