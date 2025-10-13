document.addEventListener('DOMContentLoaded', () => {
  const btn = document.querySelector('[data-menu-btn]');
  const links = document.querySelector('[data-navlinks]');
  if (btn && links) btn.addEventListener('click', () => links.classList.toggle('open'));
});
