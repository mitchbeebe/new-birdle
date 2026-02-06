// Daily Bird Game Logic

// Track correctly guessed taxonomy for filtering autocomplete
let correctTaxonomy = {
  order: null,
  family: null,
  genus: null
};

function updateCorrectTaxonomy(taxonomy) {
  if (taxonomy.order) correctTaxonomy.order = taxonomy.order;
  if (taxonomy.family) correctTaxonomy.family = taxonomy.family;
  if (taxonomy.genus) correctTaxonomy.genus = taxonomy.genus;
}

function getTaxonomyFilters() {
  const filters = {};
  if (correctTaxonomy.order) filters.order = correctTaxonomy.order;
  if (correctTaxonomy.family) filters.family = correctTaxonomy.family;
  if (correctTaxonomy.genus) filters.genus = correctTaxonomy.genus;
  return filters;
}

// Keyboard navigation for autocomplete
let selectedIndex = -1;

function initializeAutocomplete() {
  const suggestionsList = document.getElementById('suggestions');
  const guessInput = document.getElementById('guess-input');
  const autocompleteContainer = document.getElementById('autocomplete-container');
  const submitButton = document.getElementById('submit-button');

  // Hide suggestions when input loses focus, but not when tabbing to submit button
  guessInput.addEventListener('blur', (e) => {
    // Check if focus is moving to the submit button
    if (e.relatedTarget === submitButton) {
      // Clear suggestions immediately when tabbing to submit
      suggestionsList.innerHTML = '';
      selectedIndex = -1;
    } else {
      // Otherwise use timeout for mouse clicks on suggestions
      setTimeout(() => {
        suggestionsList.innerHTML = '';
        selectedIndex = -1;
      }, 200);
    }
  });

  // Reset selection when typing
  guessInput.addEventListener('input', () => {
    selectedIndex = -1;
  });

  // Keyboard navigation
  autocompleteContainer.addEventListener('keydown', (e) => {
    const items = suggestionsList.querySelectorAll('.list-group-item-action');

    // Handle Tab key to allow navigation to submit button
    if (e.key === 'Tab' && items.length > 0) {
      // Clear suggestions and allow default tab behavior
      suggestionsList.innerHTML = '';
      selectedIndex = -1;
      return; // Allow default tab behavior
    }

    if (items.length === 0) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (selectedIndex >= 0) items[selectedIndex].classList.remove('active');
      selectedIndex = Math.min(selectedIndex + 1, items.length - 1);
      items[selectedIndex].classList.add('active');
      items[selectedIndex].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (selectedIndex <= 0) return;
      items[selectedIndex].classList.remove('active');
      selectedIndex--;
      items[selectedIndex].classList.add('active');
      items[selectedIndex].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    } else if (e.key === 'Enter' && selectedIndex >= 0) {
      e.preventDefault();
      guessInput.value = items[selectedIndex].textContent.trim();
      suggestionsList.innerHTML = '';
      selectedIndex = -1;
    }
  });
}

// Hint system
function initializeHintSystem(clippy, popover) {
  clippy.addEventListener('shown.bs.popover', () => {
    const hintToast = bootstrap.Toast.getOrCreateInstance(document.getElementById('hintToast'));

    document.getElementById('hintBtn').onclick = () => {
      hintToast.show();
      popover.hide();
      document.getElementById('hint_used').value = 'true';
    };

    document.getElementById('noBtn').onclick = () => {
      popover.hide();
    };
  });
}

function updateHint(clippy, popover, hintData) {
  if (hintData.show) {
    clippy.classList.remove('visually-hidden');
    clippy.classList.add('bounce');
    setTimeout(() => clippy.classList.remove('bounce'), 500);

    // Update popover title directly
    popover._config.title = hintData.title;
    document.getElementById('hint_msg').textContent = hintData.message;

    if (hintData.message !== "The game's over. Go outside.") {
      popover.show();
    }
  }
}

// Alert system
const pluralize = (count, noun, suffix = 'es') => `${count} ${noun}${count !== 1 ? suffix : ''}`;

function showAlert(guessCount, isWinner, emojis, birdData) {
  Swal.mixin({
    title: isWinner ? "Congratulations!" : "Oh no!",
    html: isWinner ?
      `You got today's Birdle in ${pluralize(guessCount, 'guess')}.<br>Learn more about the <a href="${birdData.url}" target=_blank>${birdData.name}</a>.` :
      `Today's bird was the <a href="${birdData.url}" target=_blank>${birdData.name}</a>. But don't fret, <a href='https://birdsarentreal.com/' target=_blank>birds aren't real</a> anyway.`,
    icon: isWinner ? "success" : "error",
    confirmButtonText: "Copy Results",
    showDenyButton: true,
    denyButtonText: "Close"
  }).fire().then((result) => {
    if (result.isConfirmed) {
      navigator.clipboard.writeText(emojis);
      Swal.fire({
        toast: true,
        title: 'Copied!',
        icon: "success",
        showConfirmButton: false,
        timer: 2000,
        timerProgressBar: true
      });
    }
  });
}

// Form submission
function initializeFormSubmission(clippy, popover, birdData) {
  const guessForm = document.getElementById('guess-form');

  guessForm.addEventListener('submit', (e) => {
    e.preventDefault();
    document.getElementById('user_id').value = localStorage.getItem('user_id') || '';

    const formData = new FormData(guessForm);
    const params = new URLSearchParams(formData);

    fetch(window.location.pathname, {
      method: 'POST',
      body: params,
      headers: {
        'X-Requested-With': 'XMLHttpRequest'
      }
    })
    .then((response) => {
      if (!response.ok) {
        if (response.status === 400) {
          document.getElementById('guess-input').value = '';
          document.getElementById('suggestions').innerHTML = '';
          Swal.fire({
            toast: true,
            title: "That bird doesn't exist!",
            icon: "error",
            showConfirmButton: false,
            timer: 2000,
            timerProgressBar: true
          });
        }
        throw new Error('Request failed');
      }
      return response.json();
    })
    .then((response) => {
      document.getElementById('guesses').insertAdjacentHTML('beforeend', response.new_guess);
      document.getElementById('guess-input').value = '';
      document.getElementById('suggestions').innerHTML = '';

      // Update autocomplete filter with any correct taxonomy
      if (response.taxonomy) {
        updateCorrectTaxonomy(response.taxonomy);
      }

      // Update hint display
      if (response.hint) {
        updateHint(clippy, popover, response.hint);
      }

      // Show alert if game over
      if (response.is_winner || response.guess_count == 6) {
        showAlert(response.guess_count, response.is_winner, response.emojis, birdData);
      }
    })
    .catch(() => {
      // Error already handled above
    });
  });
}

// Initialize everything on page load
document.addEventListener('DOMContentLoaded', () => {
  const config = window.birdleConfig;

  const clippy = document.getElementById('clippy');
  const popover = new bootstrap.Popover(clippy);

  // Initialize hint system
  initializeHintSystem(clippy, popover);

  // Show initial alert if game is over
  if (config.isWinner || config.guessCount == 6) {
    showAlert(config.guessCount, config.isWinner, config.emojis, config.bird);
  }

  // Show hint if available
  updateHint(clippy, popover, config.hint);

  // Initialize autocomplete filters from existing correct guesses
  config.guesses.forEach((guess) => {
    if (guess.correctness[0]) updateCorrectTaxonomy({order: guess.order});
    if (guess.correctness[1]) updateCorrectTaxonomy({family: guess.family});
    if (guess.correctness[2]) updateCorrectTaxonomy({genus: guess.genus});
  });

  // Set up autocomplete and form submission
  initializeAutocomplete();
  initializeFormSubmission(clippy, popover, config.bird);
});
