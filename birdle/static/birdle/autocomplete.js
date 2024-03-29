// autocomplete.js

$(document).ready(function() {
    // Get the input field and initialize autocomplete
    var input = $('#guess-input');
    input.autocomplete({
      source: '/api/birds/',
      minLength: 3
    });
  });