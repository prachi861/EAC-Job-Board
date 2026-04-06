import requests
from bs4 import BeautifulSoup

# Function to scrape sources

def scrape_sources(sources):
    all_results = []
    for source in sources:
        response = requests.get(source)
        soup = BeautifulSoup(response.text, 'html.parser')
        # Assuming the required visa sponsor listings are in some specific tags
        results = soup.find_all('div', class_='visa-sponsor')
        for result in results:
            all_results.append(result.text.strip())
    return all_results

# Function to filter for visa sponsors and deduplicate

def filter_visa_sponsors(all_results):
    visa_sponsors = list(set(all_results))  # Deduplicate
    # Optionally, further filter can be applied here
    return visa_sponsors

# Main execution block

if __name__ == '__main__':
    sources = ['https://example1.com','https://example2.com','https://example3.com']  # Example sources
    all_results = scrape_sources(sources)
    visa_sponsors = filter_visa_sponsors(all_results)
    print("Visa Sponsors:")
    for sponsor in visa_sponsors:
        print(sponsor)