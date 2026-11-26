document.querySelectorAll("[data-confirm]").forEach(button => {
  button.addEventListener("click", event => {
    if (!window.confirm(button.dataset.confirm)) event.preventDefault();
  });
});
const savedAddress = document.querySelector("[data-saved-address]");
if (savedAddress) {
  const field = document.querySelector("[data-address-field]");
  const update = () => {
    field.hidden = Boolean(savedAddress.value);
    field.querySelector("textarea").required = !savedAddress.value;
  };
  savedAddress.addEventListener("change", update);
  update();
}
