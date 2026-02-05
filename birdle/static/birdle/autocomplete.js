// autocomplete.js

// Track correctly guessed taxonomy for filtering autocomplete
var correctTaxonomy = {
  order: null,
  family: null,
  genus: null
};

// Update the tracked taxonomy when a correct guess is made
function updateCorrectTaxonomy(taxonomy) {
  if (taxonomy.order) correctTaxonomy.order = taxonomy.order;
  if (taxonomy.family) correctTaxonomy.family = taxonomy.family;
  if (taxonomy.genus) correctTaxonomy.genus = taxonomy.genus;
}

// Build the autocomplete URL with taxonomy filters
function getAutocompleteUrl(term) {
  var params = new URLSearchParams();
  params.set('term', term);
  if (correctTaxonomy.order) params.set('order', correctTaxonomy.order);
  if (correctTaxonomy.family) params.set('family', correctTaxonomy.family);
  if (correctTaxonomy.genus) params.set('genus', correctTaxonomy.genus);
  return '/api/birds/?' + params.toString();
}

$(document).ready(function() {
  // Get the input field and initialize autocomplete
  var input = $('#guess-input');
  input.autocomplete({
    source: function(request, response) {
      $.ajax({
        url: getAutocompleteUrl(request.term),
        dataType: 'json',
        success: function(data) {
          response(data);
        }
      });
    },
    minLength: 3
  });
});
