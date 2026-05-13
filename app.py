import json
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI

app = FastAPI()

BASE_URL = 'https://csmobility-fbap.fujifilm.com/ords/'
LOGIN_PAGE = urljoin(BASE_URL, 'f?p=1000:101::::::&tz=7:00')

HEADERS = {
    'User-Agent': 'Mozilla/5.0'
}


def get_form_inputs(soup):
    data = {}

    for input_tag in soup.select('form input'):
        name = input_tag.get('name') or input_tag.get('id')

        if not name:
            continue

        data[name] = input_tag.get('value', '')

    return data


def find_link_by_text(soup, text):
    target = text.strip().lower()

    for anchor in soup.find_all('a'):
        anchor_text = anchor.get_text(separator=' ', strip=True).lower()

        if target in anchor_text:
            return anchor

    return None


def submit_form(session, page_url, form, extra_data=None):

    action = form.get('action') or page_url
    submit_url = urljoin(page_url, action)

    form_data = get_form_inputs(form)

    salt = form_data.pop('pSalt', None)
    protected = form_data.pop('pPageItemsProtected', '')
    row_version = form_data.pop('pPageItemsRowVersion', '')
    form_checksums = form_data.pop('pPageFormRegionChecksums', '[]')

    if extra_data:

        if salt is not None:

            items_to_submit = []

            for name, value in extra_data.items():

                if name.lower().startswith('p_'):
                    form_data[name] = value

                else:
                    items_to_submit.append({
                        'n': name,
                        'v': value
                    })

                    if name in form_data:
                        form_data.pop(name)

            try:
                checksums = json.loads(form_checksums)

            except Exception:
                checksums = []

            if items_to_submit:

                form_data['p_json'] = json.dumps({
                    'salt': salt,
                    'pageItems': {
                        'itemsToSubmit': items_to_submit,
                        'protected': protected,
                        'rowVersion': row_version,
                        'formRegionChecksums': checksums,
                    },
                })

        else:
            form_data.update(extra_data)

    response = session.post(
        submit_url,
        data=form_data,
        headers=HEADERS,
        allow_redirects=True
    )

    response.raise_for_status()

    return response


def extract_table(html):

    soup = BeautifulSoup(html, 'html.parser')

    table = soup.find(
        'table',
        {'summary': "Organization's On Hand"}
    )

    if table is None:
        return []

    headers = []

    for th in table.select('thead th'):
        headers.append(
            th.get_text(separator=' ', strip=True)
        )

    rows = []

    for tr in table.select('tbody tr'):

        cells = [
            td.get_text(separator=' ', strip=True)
for td in tr.find_all('td')
        ]

        if cells:
            rows.append(cells)

    result = []

    for row in rows:

        item = {}

        for i, value in enumerate(row):

            key = headers[i] if i < len(headers) else f'col_{i}'

            item[key] = value

        result.append(item)

    return result


@app.get("/username/{username}/password/{password}/{partnumber}")
def search_part(username, password, partnumber):

    session = requests.Session()

    # Login page
    login_page_resp = session.get(
        LOGIN_PAGE,
        headers=HEADERS
    )

    login_page_resp.raise_for_status()

    login_soup = BeautifulSoup(
        login_page_resp.text,
        'html.parser'
    )

    login_form = login_soup.find(
        'form',
        id='wwvFlowForm'
    )

    if login_form is None:
        return {
            "error": "login form not found"
        }

    # Login
    login_response = submit_form(
        session,
        LOGIN_PAGE,
        login_form,
        {
            'P101_USERNAME': username,
            'P101_PASSWORD': password,
            'p_request': 'LOGIN'
        },
    )

    home_soup = BeautifulSoup(
        login_response.text,
        'html.parser'
    )

    # Search menu
    search_link = find_link_by_text(
        home_soup,
        'Search'
    )

    if search_link is None:
        return {
            "error": "search link not found"
        }

    search_url = urljoin(
        login_response.url,
        search_link['href']
    )

    search_resp = session.get(
        search_url,
        headers=HEADERS
    )

    search_soup = BeautifulSoup(
        search_resp.text,
        'html.parser'
    )

    search_item_link = find_link_by_text(
        search_soup,
        'Search Item'
    )

    if search_item_link is None:
        return {
            "error": "search item link not found"
        }

    search_item_url = urljoin(
        search_resp.url,
        search_item_link['href']
    )

    search_item_resp = session.get(
        search_item_url,
        headers=HEADERS
    )

    search_item_soup = BeautifulSoup(
        search_item_resp.text,
        'html.parser'
    )

    search_form = search_item_soup.find(
        'form',
        id='wwvFlowForm'
    )

    if search_form is None:
        return {
            "error": "search form not found"
        }

    search_response = submit_form(
        session,
        search_item_resp.url,
        search_form,
        {
            'P3000_P_PART_NUMBER': partnumber,
            'p_request': 'SEARCH'
        },
    )

    soup = BeautifulSoup(
        search_response.text,
        'html.parser'
    )

    row = soup.find(
        'td',
        string=lambda t: t and partnumber in t.strip()
    )

    if not row:
        return {
            "error": "part not found"
        }

    details_link = row.find_next(
        'a',
        string=lambda t: t and 'Details' in t.strip()
    )

    if not details_link:
return {
            "error": "details link not found"
        }

    details_url = urljoin(
        search_response.url,
        details_link['href']
    )

    details_response = session.get(
        details_url,
        headers=HEADERS
    )

    data = extract_table(details_response.text)

    return {
        "partnumber": partnumber,
        "data": data
    }