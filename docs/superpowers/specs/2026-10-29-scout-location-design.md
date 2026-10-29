# Scout selection and financial location panel

## Intent

Let an investor select a Scout listing without losing the search inventory, then evaluate the financial case with a clear, trustworthy view of where the property is located.

## Goals

- Selecting a validated Scout listing creates its analysis workflow while keeping the investor on Scout.
- Place a location panel immediately below the negotiation tactic in Financial Estimates.
- Use the listing's exact address only when it is explicitly available; otherwise show the postcode area.
- Explain the available location evidence concisely without inventing neighbourhood claims.

## Non-goals

- No live Keenable calls.
- No inferred street address, parcel boundary, neighbourhood rating, commute estimate, or investment recommendation.
- No third-party geocoding of listing addresses.

## Approaches considered

1. Privacy-first map (selected): use the local postcode coordinate index for a postcode-centre map marker, and only expose a full address when the listing already states it. The panel labels the precision clearly.
2. Externally geocode every listing: rejected because it transmits listing addresses to another service and can overstate uncertain data.
3. No map: rejected because it makes it harder to orient an investor geographically.

## Design

- Scout selection remains on the Scout view, disables the selected button while work starts, and confirms that the deal was added to Analyze.
- The Financial Estimates location panel follows negotiation tactic.
- A map is embedded from OpenStreetMap at the coordinate precision known locally. A postcode marker is labelled `Postcode-area location`; an explicit listing address is presented as `Listing address` but is not externally geocoded.
- The short note names the city and postcode, tells the user whether the location is postcode-level or address-level, and says to verify the exact position with the seller or broker when needed.
- If no local coordinate is available, the panel keeps the location label and explains that a map is unavailable rather than guessing.

## Constraints

- The external map loads only in the investor's browser.
- Existing deal actions, financial calculations, and data sources remain unchanged.
